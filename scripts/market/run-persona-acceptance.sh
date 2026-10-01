#!/usr/bin/env bash
# Finite persona acceptance; production access is bounded GET and read-only SQL.
set -euo pipefail
set +m
fail() { printf '%s\n' "$*" >&2; exit 2; }
original_args=("$@")
mapping='' credential_file='' run_root=''
while (($#)); do
  case "$1" in
    --mapping|--env-file|--run-root)
      (($# >= 2)) && [[ "$2" != --* ]] || fail "Missing value for $1"
      case "$1" in
        --mapping) [[ -z "$mapping" ]] || fail 'Duplicate --mapping'; mapping="$2" ;;
        --env-file) [[ -z "$credential_file" ]] || fail 'Duplicate --env-file'; credential_file="$2" ;;
        --run-root) [[ -z "$run_root" ]] || fail 'Duplicate --run-root'; run_root="$2" ;;
      esac
      shift 2 ;;
    *) fail 'Usage: run-persona-acceptance.sh --mapping FILE --env-file FILE --run-root /tmp/prep-watchdeck-persona-ID' ;;
  esac
done
[[ -n "$mapping" && -n "$credential_file" && -n "$run_root" ]] || fail 'All three arguments are required'
[[ "$run_root" =~ ^/tmp/prep-watchdeck-persona-[A-Za-z0-9_-]+$ ]] || fail 'Use a fresh canonical /tmp persona run root'
[[ "$(realpath -m -- "$run_root")" == "$run_root" && ! -e "$run_root" ]] || fail 'Run root exists or is not canonical'
[[ -f "$mapping" && -r "$mapping" && -f "$credential_file" && -r "$credential_file" ]] || fail 'Input files must exist and be readable'
command -v setsid >/dev/null || fail 'setsid is required for owned process groups'
if [[ "${PREP_WATCHDECK_PERSONA_BOUNDED:-0}" != 1 ]]; then
  exec env PREP_WATCHDECK_PERSONA_BOUNDED=1 timeout --signal=TERM --kill-after=10s 900s bash "$0" "${original_args[@]}"
fi
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
[[ "$repo_root" != "$HOME/releases" && "$repo_root" != "$HOME/releases/"* ]] || fail 'Use a development checkout outside releases'
mapping=$(realpath -e -- "$mapping")
credential_file=$(realpath -e -- "$credential_file")
ranking_state="$repo_root/var/tmp/persona-${run_root##*/prep-watchdeck-persona-}/ranking"
[[ ! -e "$ranking_state" ]] || fail 'Dedicated ranking state exists; choose a new run ID'
cd -- "$repo_root"
uv run --no-sync --package prep-watchdeck-market python - <<'PY'
import socket
for port in (4174, 4178, 8870):
    with socket.socket() as connection:
        try: connection.bind(('127.0.0.1', port))
        except OSError: raise SystemExit(f'Required isolated port {port} is occupied')
PY
umask 077
mkdir -- "$run_root"
declare -A children=()
last_pid=''
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  for pid in "${!children[@]}"; do kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; done
  local deadline=$((SECONDS + 3)) live
  while ((SECONDS < deadline)); do
    live=0
    for pid in "${!children[@]}"; do if kill -0 -- "-$pid" 2>/dev/null; then live=1; fi; done
    ((live)) || break
    sleep 0.1
  done
  for pid in "${!children[@]}"; do kill -KILL -- "-$pid" 2>/dev/null || true; done
  for pid in "${!children[@]}"; do wait "$pid" 2>/dev/null || true; done
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start_child() {
  local label="$1" marker; shift
  marker="$run_root/$label.pgid"
  setsid bash -c '[[ "$(ps -o pgid= -p "$$" | tr -d "[:space:]")" == "$$" ]] || exit 2; printf "%s\n" "$$" > "$1"; shift; exec "$@"' owned-session "$marker" "$@" <&0 >"$run_root/$label.log" 2>&1 &
  last_pid=$!
  children["$last_pid"]="$label"
  for attempt in {1..100}; do [[ -f "$marker" ]] && break; sleep 0.01; done
  [[ -f "$marker" && "$(<"$marker")" == "$last_pid" ]] || fail 'Owned session PID/PGID handshake failed'
  printf '%s\t%s\t%s\n' "$label" "$last_pid" "$last_pid" >>"$run_root/pids.tsv"
}
wait_child() {
  local pid="$1" result=0 label="${children[$1]}"
  wait "$pid" || result=$?
  kill -TERM -- "-$pid" 2>/dev/null || true
  for attempt in {1..50}; do kill -0 -- "-$pid" 2>/dev/null || break; sleep 0.05; done
  kill -KILL -- "-$pid" 2>/dev/null || true
  unset "children[$pid]"
  ((result == 0)) || printf 'Failed: %s; see %s/%s.log\n' "$label" "$run_root" "$label" >&2
  return "$result"
}
run_step() { start_child "$@"; wait_child "$last_pid"; }
mkdir -- "$run_root/source"
cp --parents -t "$run_root/source" scripts/market/{run-persona-acceptance.sh,observe-live-markets.py,probe-live-endpoints.py} scripts/ranking/{prepare-persona-map.py,verify-live-values.py} apps/web/playwright.persona.config.ts apps/web/tests/acceptance/markets-persona.e2e.ts apps/web/tests/e2e/universe-explorer.e2e.ts apps/web/tests/e2e/helpers/browser-ime.ts
cd -- "$repo_root/apps/web"
run_step build bun run build
run_step browser-ime env PREP_WATCHDECK_FULL_E2E=1 bun run test:e2e universe-explorer.e2e.ts -g 'P01|P02' --output="$run_root/browser-ime"
cd -- "$repo_root"
run_step prepare-map uv run --no-sync --package prep-watchdeck-ranking python scripts/ranking/prepare-persona-map.py --mapping "$mapping" --state-dir "$ranking_state"
start_child observer uv run --no-sync --package prep-watchdeck-market python scripts/market/observe-live-markets.py --state-dir "$run_root/market" --evidence-dir "$run_root/live" --mapping "$mapping" --ranking-port 8769
observer_pid="$last_pid"
observer_started=$SECONDS
start_child native uv run --no-sync --package prep-watchdeck-market python scripts/market/probe-live-endpoints.py --env-file "$credential_file" --state-dir "$run_root/market" --evidence-dir "$run_root/native" --seconds 360
native_pid="$last_pid"
start_child ranking uv run --no-sync --package prep-watchdeck-ranking python scripts/ranking/run-isolated.py --mapping "$ranking_state/sample-map.json" --state-dir "$ranking_state" --original-state-dir "$run_root/market" --port 8870 --run-seconds 420
ranking_pid="$last_pid"
run_step readiness uv run --no-sync --package prep-watchdeck-market python - "$run_root" "$observer_pid" "$native_pid" "$ranking_pid" <<'PY'
import json, os, sys, time, urllib.request
from pathlib import Path
root=Path(sys.argv[1]); deadline=time.monotonic()+150
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
while time.monotonic()<deadline:
    for pid in sys.argv[2:]:
        try: os.kill(int(pid), 0)
        except ProcessLookupError: raise SystemExit('An observation worker exited before readiness')
    try:
        ready=json.loads((root/'live/ready.json').read_text())
        metrics=json.loads((root/'market/artifacts/market-metrics.json').read_text())
        with opener.open('http://127.0.0.1:8870/rankings?period=15m&order=turnover',timeout=2) as response:
            ranking=json.load(response)
        rows=ranking['rows']
        if ready['status']=='ready' and metrics['schemaVersion']==1 and ranking['schemaVersion']=='ranking-v3' and {r['asset'] for r in rows}=={'BTC','ETH','PEPE','BTCDOM'} and next(r for r in rows if r['asset']=='BTC')['state']=='ready':
            print('Actual artifact, native metrics, and bounded ranking are ready'); break
    except (OSError, ValueError, KeyError, StopIteration): pass
    time.sleep(1)
else: raise SystemExit('Actual-data readiness timed out; no fixture substitution')
PY
cd -- "$repo_root"
run_step verify-sample-values uv run --no-sync --package prep-watchdeck-ranking python scripts/ranking/verify-live-values.py --port 8870 --asset BTC --asset ETH --asset PEPE --output "$run_root/reference-sample-values.json"
run_step verify-live-values uv run --no-sync --package prep-watchdeck-ranking python scripts/ranking/verify-live-values.py --port 8769 --asset BTC --asset ETH --asset PEPE --output "$run_root/reference-live-values.json"
export PREP_WATCHDECK_PERSONA_STATE_DIR="$run_root/market" PREP_WATCHDECK_PERSONA_RANKING_PORT=8870
cd -- "$repo_root/apps/web"
primary_budget=$((300 - (SECONDS - observer_started)))
((primary_budget > 0)) || fail 'Observation budget exhausted before primary flow; use a new run'
run_step browser-primary timeout --signal=TERM --kill-after=5s "${primary_budget}s" bun run test:e2e --config playwright.persona.config.ts -g 'P00|P01|P02'
cp -a -- "$run_root/browser" "$run_root/browser-before-restart"
cp -- "$run_root/browser-results.json" "$run_root/browser-before-restart-results.json"
run_step persistence uv run --no-sync --package prep-watchdeck-market python - "$run_root" <<'PY'
import json, sys
from pathlib import Path
root=Path(sys.argv[1]); notes=None
for file in (root/'market/past-notes').glob('*.json'):
    payload=json.loads(file.read_text())
    if payload.get('venueInstrumentId')=='bitget:BTCUSDT': notes=payload['notes']; break
if not notes: raise SystemExit('Expected own persisted BTC notes are missing')
workspace=json.loads((root/'market/user-workspace.json').read_text())
(root/'persistence-before-restart.json').write_text(json.dumps({'notes':notes,'workspace':workspace},ensure_ascii=False))
PY
restart_budget=$((350 - (SECONDS - observer_started)))
((restart_budget > 0)) || fail 'Observation budget exhausted before restart; use a new run'
run_step browser-restart timeout --signal=TERM --kill-after=5s "${restart_budget}s" bun run test:e2e --config playwright.persona.config.ts -g P03
wait_child "$observer_pid"
wait_child "$native_pid"
printf 'Persona checks completed. Evidence: %s; isolated ranking state: %s\n' "$run_root" "$ranking_state"
