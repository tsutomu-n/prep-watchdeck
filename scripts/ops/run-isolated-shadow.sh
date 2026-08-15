#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

mode="dry-run"
repo_root="$DEFAULT_REPO_ROOT"
state_root=""
evidence_root=""
live_state_root=""
live_snapshot=""
live_duckdb=""
live_scanner_unit=""
compose_project=""
db_port=""
web_port=""
baseline_seconds=900
shadow_seconds=3600
sample_seconds=5
docker_bin="${DOCKER_BIN:-/usr/bin/docker}"
systemctl_bin="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"
uv_bin="${UV_BIN:-$HOME/.local/bin/uv}"
bun_bin="${BUN_BIN:-$HOME/.local/share/bun/bin/bun}"
curl_bin="${CURL_BIN:-/usr/bin/curl}"
lsof_bin="${LSOF_BIN:-/usr/bin/lsof}"

usage() {
  printf '%s\n' \
    "Usage: $0 --dry-run|--execute --state-root PATH --evidence-root PATH" \
    "          --live-state-root PATH --live-snapshot PATH --live-duckdb PATH" \
    "          --live-scanner-unit UNIT --compose-project NAME" \
    "          --db-port PORT --web-port PORT [--repo-root PATH]" \
    "          [--baseline-seconds N] [--shadow-seconds N] [--sample-seconds N]" \
    "" \
    "Default mode is dry-run. Default durations are 15-minute baseline and 60-minute shadow."
}

require_value() {
  if [[ $# -lt 2 || -z "$2" ]]; then
    printf 'missing value for %s\n' "$1" >&2
    usage >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) mode="dry-run"; shift ;;
    --execute) mode="execute"; shift ;;
    --repo-root) require_value "$@"; repo_root="$2"; shift 2 ;;
    --state-root) require_value "$@"; state_root="$2"; shift 2 ;;
    --evidence-root) require_value "$@"; evidence_root="$2"; shift 2 ;;
    --live-state-root) require_value "$@"; live_state_root="$2"; shift 2 ;;
    --live-snapshot) require_value "$@"; live_snapshot="$2"; shift 2 ;;
    --live-duckdb) require_value "$@"; live_duckdb="$2"; shift 2 ;;
    --live-scanner-unit) require_value "$@"; live_scanner_unit="$2"; shift 2 ;;
    --compose-project) require_value "$@"; compose_project="$2"; shift 2 ;;
    --db-port) require_value "$@"; db_port="$2"; shift 2 ;;
    --web-port) require_value "$@"; web_port="$2"; shift 2 ;;
    --baseline-seconds) require_value "$@"; baseline_seconds="$2"; shift 2 ;;
    --shadow-seconds) require_value "$@"; shadow_seconds="$2"; shift 2 ;;
    --sample-seconds) require_value "$@"; sample_seconds="$2"; shift 2 ;;
    --docker-bin) require_value "$@"; docker_bin="$2"; shift 2 ;;
    --systemctl-bin) require_value "$@"; systemctl_bin="$2"; shift 2 ;;
    --uv-bin) require_value "$@"; uv_bin="$2"; shift 2 ;;
    --bun-bin) require_value "$@"; bun_bin="$2"; shift 2 ;;
    --curl-bin) require_value "$@"; curl_bin="$2"; shift 2 ;;
    --lsof-bin) require_value "$@"; lsof_bin="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

required=(
  state_root evidence_root live_state_root live_snapshot live_duckdb live_scanner_unit
  compose_project db_port web_port
)
for name in "${required[@]}"; do
  if [[ -z "${!name}" ]]; then
    printf 'required argument is missing: %s\n' "$name" >&2
    usage >&2
    exit 2
  fi
done

require_absolute_path() {
  local label="$1"
  local value="$2"
  if [[ "$value" != /* || "$value" == *$'\n'* ]]; then
    printf '%s must be an absolute single-line path: %s\n' "$label" "$value" >&2
    exit 2
  fi
}

for item in \
  "repo root:$repo_root" \
  "shadow state root:$state_root" \
  "evidence root:$evidence_root" \
  "live state root:$live_state_root" \
  "live snapshot:$live_snapshot" \
  "live DuckDB:$live_duckdb" \
  "docker binary:$docker_bin" \
  "systemctl binary:$systemctl_bin" \
  "uv binary:$uv_bin" \
  "bun binary:$bun_bin" \
  "curl binary:$curl_bin" \
  "lsof binary:$lsof_bin"; do
  require_absolute_path "${item%%:*}" "${item#*:}"
done

canonical_path() {
  realpath -m -- "$1"
}

repo_root="$(canonical_path "$repo_root")"
state_root="$(canonical_path "$state_root")"
evidence_root="$(canonical_path "$evidence_root")"
live_state_root="$(canonical_path "$live_state_root")"
live_snapshot="$(canonical_path "$live_snapshot")"
live_duckdb="$(canonical_path "$live_duckdb")"

is_within() {
  local child="$1"
  local parent="$2"
  [[ "$child" == "$parent" || "$child" == "$parent"/* ]]
}

if is_within "$state_root" "$repo_root" || is_within "$repo_root" "$state_root" || \
   is_within "$evidence_root" "$repo_root" || is_within "$repo_root" "$evidence_root"; then
  printf 'shadow state and evidence roots must remain outside the repository\n' >&2
  exit 2
fi
if is_within "$state_root" "$live_state_root" || is_within "$live_state_root" "$state_root"; then
  printf 'shadow state root must not overlap the live state root\n' >&2
  exit 2
fi
if is_within "$evidence_root" "$state_root" || is_within "$state_root" "$evidence_root"; then
  printf 'evidence root and shadow state root must be separate\n' >&2
  exit 2
fi
if is_within "$evidence_root" "$live_state_root" || \
   is_within "$live_state_root" "$evidence_root"; then
  printf 'evidence root must not overlap the live state root\n' >&2
  exit 2
fi
if ! is_within "$live_snapshot" "$live_state_root" || ! is_within "$live_duckdb" "$live_state_root"; then
  printf 'live snapshot and DuckDB must resolve below the explicit live state root\n' >&2
  exit 2
fi

require_positive_integer() {
  local label="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    printf '%s must be a positive integer\n' "$label" >&2
    exit 2
  fi
}

require_port() {
  local label="$1"
  local value="$2"
  require_positive_integer "$label" "$value"
  if (( value > 65535 )); then
    printf '%s must be within the TCP port range\n' "$label" >&2
    exit 2
  fi
}

require_port "DB port" "$db_port"
require_port "Web port" "$web_port"
require_positive_integer "baseline seconds" "$baseline_seconds"
require_positive_integer "shadow seconds" "$shadow_seconds"
require_positive_integer "sample seconds" "$sample_seconds"
if (( db_port == 5432 || db_port == 55432 )); then
  printf 'DB port must not use JustPass 5432 or production default 55432\n' >&2
  exit 2
fi
if (( web_port == 5173 )); then
  printf 'Web port must not use the production default 5173\n' >&2
  exit 2
fi
if (( db_port == web_port )); then
  printf 'DB and Web ports must be different\n' >&2
  exit 2
fi
production_state_root="$(canonical_path "$HOME/.local/share/prep-watchdeck-market")"
if [[ "$state_root" == "$production_state_root" ]]; then
  printf 'shadow state root must not use the production default\n' >&2
  exit 2
fi
if [[ "$live_scanner_unit" == "prep-watchdeck-market.service" ]]; then
  printf 'live scanner baseline must not point at the replacement production unit\n' >&2
  exit 2
fi
if [[ ! "$compose_project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || \
   [[ "$compose_project" == "prep-watchdeck-market" ]]; then
  printf 'Compose project must be a non-production lowercase shadow name\n' >&2
  exit 2
fi

printf 'mode=%s\n' "$mode"
printf 'repoRoot=%s\n' "$repo_root"
printf 'shadowStateRoot=%s\n' "$state_root"
printf 'evidenceRoot=%s\n' "$evidence_root"
printf 'liveStateRoot=%s\n' "$live_state_root"
printf 'liveSnapshot=%s\n' "$live_snapshot"
printf 'liveDuckDB=%s\n' "$live_duckdb"
printf 'liveScannerUnit=%s\n' "$live_scanner_unit"
printf 'composeProject=%s dbPort=%s webPort=%s\n' "$compose_project" "$db_port" "$web_port"
printf 'baselineSeconds=%s shadowSeconds=%s sampleSeconds=%s\n' \
  "$baseline_seconds" "$shadow_seconds" "$sample_seconds"
printf 'databaseOverride=PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=true\n'
printf 'webMode=build-once-before-baseline-then-preview\n'
printf 'dockerHost=unix:///var/run/docker.sock dockerContext=unset\n'

if [[ "$mode" == "dry-run" ]]; then
  printf 'dry-run: no directory, container, process, API, database, service, or Git mutation performed\n'
  exit 0
fi

if [[ ! -S /var/run/docker.sock ]]; then
  printf 'rootful local Docker socket is unavailable: /var/run/docker.sock\n' >&2
  exit 2
fi
unset DOCKER_CONTEXT
export DOCKER_HOST="unix:///var/run/docker.sock"

for executable in \
  "$docker_bin" "$systemctl_bin" "$uv_bin" "$bun_bin" "$curl_bin" "$lsof_bin" \
  /usr/bin/python3 /usr/bin/stat /usr/bin/ss /usr/bin/openssl /usr/bin/setsid \
  /usr/bin/sha256sum; do
  if [[ ! -x "$executable" ]]; then
    printf 'required executable is unavailable: %s\n' "$executable" >&2
    exit 2
  fi
done
if [[ ! -d "$repo_root/apps/market-core" || ! -f "$repo_root/deploy/market-postgres/compose.yaml" ]]; then
  printf 'repo root does not contain the market replacement runtime\n' >&2
  exit 2
fi
if [[ ! -d "$live_state_root" || ! -r "$live_snapshot" || ! -r "$live_duckdb" ]]; then
  printf 'explicit live read-only evidence paths are unavailable\n' >&2
  exit 2
fi
if [[ -e "$state_root" ]] && find "$state_root" -mindepth 1 -print -quit | grep -q .; then
  printf 'shadow state root must be absent or empty: %s\n' "$state_root" >&2
  exit 2
fi
if /usr/bin/ss -H -ltn "sport = :$db_port" | grep -q . || \
   /usr/bin/ss -H -ltn "sport = :$web_port" | grep -q .; then
  printf 'a requested shadow port is already in use\n' >&2
  exit 2
fi
if [[ -n "$("$docker_bin" compose \
  -f "$repo_root/deploy/market-postgres/compose.yaml" \
  -p "$compose_project" ps -q 2>/dev/null)" ]]; then
  printf 'Compose project is already in use: %s\n' "$compose_project" >&2
  exit 2
fi

live_state="$($systemctl_bin --user show "$live_scanner_unit" \
  -p ActiveState --value 2>/dev/null || true)"
if [[ "$live_state" != "active" ]]; then
  printf 'explicit live scanner unit is not active: %s\n' "$live_scanner_unit" >&2
  exit 2
fi

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$(/usr/bin/openssl rand -hex 4)"
evidence_dir="$evidence_root/$run_id"
postgres_env="$state_root/shadow-postgres.env"
compose_file="$repo_root/deploy/market-postgres/compose.yaml"
market_pid=""
market_pgid=""
web_pid=""
web_pgid=""
compose_started=0
shell_pgid="$(ps -o pgid= -p $$ | tr -d ' ')"

workspace_source_digest() {
  (
    git -C "$repo_root" rev-parse HEAD
    git -C "$repo_root" diff --binary --no-ext-diff --full-index HEAD --
    while IFS= read -r -d '' path; do
      printf 'untracked:%s\0' "$path"
      /usr/bin/sha256sum -- "$repo_root/$path" | cut -d ' ' -f 1
    done < <(git -C "$repo_root" ls-files --others --exclude-standard -z)
  ) | /usr/bin/sha256sum | cut -d ' ' -f 1
}

kill_owned_group() {
  local leader_pid="$1"
  local pgid="$2"
  if [[ "$pgid" =~ ^[1-9][0-9]*$ && "$pgid" != "$shell_pgid" ]] && \
     kill -0 -- "-$pgid" 2>/dev/null; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
    for _ in {1..15}; do
      if ! kill -0 -- "-$pgid" 2>/dev/null; then
        [[ -n "$leader_pid" ]] && wait "$leader_pid" 2>/dev/null || true
        return
      fi
      sleep 1
    done
    kill -KILL -- "-$pgid" 2>/dev/null || true
    [[ -n "$leader_pid" ]] && wait "$leader_pid" 2>/dev/null || true
  fi
  return 0
}

cleanup() {
  local status="${1:-$?}"
  trap - EXIT INT TERM
  kill_owned_group "$web_pid" "$web_pgid"
  kill_owned_group "$market_pid" "$market_pgid"
  if (( compose_started == 1 )); then
    PREP_WATCHDECK_MARKET_STATE_DIR="$state_root" \
    PREP_WATCHDECK_MARKET_ENV_FILE="$postgres_env" \
    PREP_WATCHDECK_MARKET_DB_PORT="$db_port" \
      "$docker_bin" compose -f "$compose_file" -p "$compose_project" down \
        --remove-orphans >/dev/null 2>&1 || true
  fi
  printf 'cleanup=owned-pids-and-compose-project-only status=%s\n' "$status"
  exit "$status"
}
trap cleanup EXIT
trap 'cleanup 130' INT
trap 'cleanup 143' TERM

umask 077
install -d -m 0700 "$state_root" "$state_root/postgres" "$state_root/tmp" "$evidence_dir"
shadow_password="$(/usr/bin/openssl rand -hex 24)"
shadow_user="prep_watchdeck_market_shadow"
shadow_database="prep_watchdeck_market_shadow"
printf 'POSTGRES_DB=%s\nPOSTGRES_USER=%s\nPOSTGRES_PASSWORD=%s\n' \
  "$shadow_database" "$shadow_user" "$shadow_password" >"$postgres_env"
chmod 0600 "$postgres_env"
database_url="postgresql://$shadow_user:$shadow_password@127.0.0.1:$db_port/$shadow_database"

{
  printf 'runId=%s\n' "$run_id"
  printf 'startedAt=%s\n' "$(date --iso-8601=seconds)"
  printf 'branch=%s\n' "$(git -C "$repo_root" branch --show-current)"
  printf 'head=%s\n' "$(git -C "$repo_root" rev-parse HEAD)"
  printf 'repoRoot=%s\nstateRoot=%s\nevidenceDir=%s\n' \
    "$repo_root" "$state_root" "$evidence_dir"
  printf 'composeProject=%s\ndbPort=%s\nwebPort=%s\n' \
    "$compose_project" "$db_port" "$web_port"
  printf 'liveScannerUnit=%s\nliveSnapshot=%s\nliveDuckDB=%s\n' \
    "$live_scanner_unit" "$live_snapshot" "$live_duckdb"
  printf 'baselineSeconds=%s\nshadowSeconds=%s\nsampleSeconds=%s\n' \
    "$baseline_seconds" "$shadow_seconds" "$sample_seconds"
  printf 'databaseOverride=true\nprivateApiOrTradingCredential=false\n'
  printf 'dockerHost=unix:///var/run/docker.sock\ndockerContext=unset\n'
} >"$evidence_dir/run-metadata.env"
git -C "$repo_root" status --short >"$evidence_dir/git-status-before.txt"
source_digest_before="$(workspace_source_digest)"
printf '%s\n' "$source_digest_before" >"$evidence_dir/source-digest-before.txt"

(
  cd "$repo_root/apps/web"
  "$bun_bin" run build
) >"$evidence_dir/web-build.log" 2>&1
df -PB1 "$state_root" >"$evidence_dir/disk-before.txt"
free_start_bytes="$(df -B1 --output=avail "$state_root" | tail -n 1 | tr -d ' ')"

read_host_network() {
  awk -F'[: ]+' 'NR > 2 {rx += $3; tx += $11} END {printf "%d %d", rx, tx}' /proc/net/dev
}

sample_runtime() {
  local duration="$1"
  local output="$2"
  local service_pid="${3:-}"
  local explorer_pid="${4:-}"
  local deadline=$(( $(date +%s) + duration ))
  printf 'sampledAt\tsnapshotMtime\tnRestarts\tduckdbOpeners\thostRxBytes\thostTxBytes\tmarketCpuPct\tmarketRssKb\twebCpuPct\twebRssKb\n' >"$output"
  while :; do
    local now snapshot_mtime restarts openers network market_cpu market_rss web_cpu web_rss
    now="$(date +%s)"
    snapshot_mtime="$(stat -c %Y "$live_snapshot")"
    restarts="$($systemctl_bin --user show "$live_scanner_unit" -p NRestarts --value)"
    openers="$({ "$lsof_bin" -t -- "$live_duckdb" 2>/dev/null || true; } | sort -u | wc -l)"
    network="$(read_host_network)"
    market_cpu=0
    market_rss=0
    web_cpu=0
    web_rss=0
    if [[ -n "$service_pid" ]] && kill -0 "$service_pid" 2>/dev/null; then
      read -r market_cpu market_rss < <(ps -p "$service_pid" -o %cpu=,rss=)
    fi
    if [[ -n "$explorer_pid" ]] && kill -0 "$explorer_pid" 2>/dev/null; then
      read -r web_cpu web_rss < <(ps -p "$explorer_pid" -o %cpu=,rss=)
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$now" "$snapshot_mtime" "$restarts" "$openers" $network \
      "$market_cpu" "$market_rss" "$web_cpu" "$web_rss" >>"$output"
    if (( now >= deadline )); then
      break
    fi
    sleep_for="$sample_seconds"
    if (( now + sleep_for > deadline )); then
      sleep_for=$((deadline - now))
    fi
    (( sleep_for > 0 )) && sleep "$sleep_for"
  done
}

printf 'baseline=start\n'
sample_runtime "$baseline_seconds" "$evidence_dir/baseline.tsv"
printf 'baseline=complete\n'

export PREP_WATCHDECK_MARKET_STATE_DIR="$state_root"
export PREP_WATCHDECK_MARKET_ENV_FILE="$postgres_env"
export PREP_WATCHDECK_MARKET_DB_PORT="$db_port"
"$docker_bin" compose -f "$compose_file" -p "$compose_project" up -d postgres \
  >"$evidence_dir/compose-up.log" 2>&1
compose_started=1
container_id="$($docker_bin compose -f "$compose_file" -p "$compose_project" ps -q postgres)"
for _ in {1..30}; do
  health="$($docker_bin inspect -f '{{.State.Health.Status}}' "$container_id" 2>/dev/null || true)"
  [[ "$health" == "healthy" ]] && break
  sleep 2
done
if [[ "${health:-}" != "healthy" ]]; then
  printf 'isolated Postgres did not become healthy\n' >&2
  exit 1
fi

market_environment=(
  "PREP_WATCHDECK_MARKET_DATABASE_URL=$database_url"
  "PREP_WATCHDECK_MARKET_STATE_DIR=$state_root"
  "PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=true"
)
(
  cd "$repo_root/apps/market-core"
  env "${market_environment[@]}" "$uv_bin" run watchdeck-market migrate
) >"$evidence_dir/migrate.log" 2>&1

query_database() {
  local query="$1"
  "$docker_bin" compose -f "$compose_file" -p "$compose_project" exec -T \
    -e "PGPASSWORD=$shadow_password" postgres \
    psql -X -qAt -h 127.0.0.1 -U "$shadow_user" -d "$shadow_database" -c "$query"
}

raw_relation_bytes() {
  query_database "
    WITH raw_leaf_relations AS (
      SELECT relid
      FROM pg_partition_tree('raw_market_observations'::regclass)
      WHERE isleaf

      UNION ALL

      SELECT relid
      FROM pg_partition_tree('selected_raw_observations'::regclass)
      WHERE isleaf
    )
    SELECT coalesce(sum(pg_total_relation_size(relid)), 0)
    FROM raw_leaf_relations
  "
}

db_start_bytes="$(query_database "SELECT pg_database_size(current_database())")"
raw_start_bytes="$(raw_relation_bytes)"

(
  cd "$repo_root/apps/market-core"
  exec /usr/bin/setsid env "${market_environment[@]}" \
    "$uv_bin" run watchdeck-market service
) >"$evidence_dir/market-service.log" 2>&1 &
market_pid=$!
sleep 1
market_pgid="$(ps -o pgid= -p "$market_pid" | tr -d ' ')"
if [[ -z "$market_pgid" || "$market_pgid" == "$shell_pgid" ]]; then
  printf 'isolated market service did not enter its owned process group\n' >&2
  exit 1
fi

for _ in {1..90}; do
  if ! kill -0 "$market_pid" 2>/dev/null; then
    printf 'isolated market service exited during startup\n' >&2
    exit 1
  fi
  [[ -s "$state_root/artifacts/universe-snapshot.json" ]] && break
  sleep 1
done
if [[ ! -s "$state_root/artifacts/universe-snapshot.json" ]]; then
  printf 'isolated market service did not publish an artifact\n' >&2
  exit 1
fi

(
  cd "$repo_root/apps/web"
  exec /usr/bin/setsid env PREP_WATCHDECK_MARKET_STATE_DIR="$state_root" PORT="$web_port" \
    "$bun_bin" run preview -- --port "$web_port" --strictPort
) >"$evidence_dir/web.log" 2>&1 &
web_pid=$!
sleep 1
web_pgid="$(ps -o pgid= -p "$web_pid" | tr -d ' ')"
if [[ -z "$web_pgid" || "$web_pgid" == "$shell_pgid" ]]; then
  printf 'isolated Web did not enter its owned process group\n' >&2
  exit 1
fi
for _ in {1..60}; do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    printf 'isolated Web exited during startup\n' >&2
    exit 1
  fi
  if "$curl_bin" -fsS "http://127.0.0.1:$web_port/" \
    -o "$evidence_dir/web-smoke.html"; then
    break
  fi
  sleep 1
done
if [[ ! -s "$evidence_dir/web-smoke.html" ]]; then
  printf 'isolated Web did not answer on its dedicated port\n' >&2
  exit 1
fi

printf 'shadow=start\n'
sample_runtime "$shadow_seconds" "$evidence_dir/shadow.tsv" "$market_pid" "$web_pid"
printf 'shadow=complete\n'
if ! kill -0 "$market_pid" 2>/dev/null || ! kill -0 "$web_pid" 2>/dev/null; then
  printf 'an isolated shadow process exited before evidence collection\n' >&2
  exit 1
fi

db_end_bytes="$(query_database "SELECT pg_database_size(current_database())")"
raw_end_bytes="$(raw_relation_bytes)"
query_database "
  SELECT run_kind, status, count(*),
         round(extract(epoch FROM max(completed_at - started_at))::numeric, 3)
  FROM collector_runs
  GROUP BY run_kind, status
  ORDER BY run_kind, status;
  SELECT instrument.venue, state.status, count(*)
  FROM latest_market_state AS state
  JOIN venue_instrument_versions AS instrument USING (venue_instrument_version_id)
  WHERE instrument.valid_to IS NULL
  GROUP BY instrument.venue, state.status
  ORDER BY instrument.venue, state.status;
  SELECT 'market_state_1m', count(*) FROM market_state_1m
  UNION ALL SELECT 'candle_1m', count(*) FROM candle_1m
  UNION ALL SELECT 'funding_events', count(*) FROM funding_events;
" >"$evidence_dir/database-summary.tsv"

(
  cd "$repo_root/apps/market-core"
  env "${market_environment[@]}" "$uv_bin" run python \
    -m prep_watchdeck_market.capacity_sample --pretty
) >"$evidence_dir/capacity.json"

awk '
  {
    line = $0
    while (match(line, /error_codes=[^[:space:]]+/)) {
      field = substr(line, RSTART + 12, RLENGTH - 12)
      count_codes = split(field, codes, ",")
      for (position = 1; position <= count_codes; position++) {
        if (codes[position] ~ /:(http_429|bitget_business_429)$/) {
          count++
        }
      }
      line = substr(line, RSTART + RLENGTH)
    }
  }
  END { print count + 0 }
' "$evidence_dir/market-service.log" >"$evidence_dir/http-429-count.txt"
http_429_count="$(tr -d ' ' <"$evidence_dir/http-429-count.txt")"

/usr/bin/python3 - \
  "$evidence_dir/baseline.tsv" "$evidence_dir/shadow.tsv" "$evidence_dir/capacity.json" \
  "$evidence_dir/summary.json" "$baseline_seconds" "$shadow_seconds" \
  "$raw_start_bytes" "$raw_end_bytes" "$db_start_bytes" "$db_end_bytes" \
  "$free_start_bytes" "$http_429_count" <<'PY'
import csv
import json
import math
import statistics
import sys
from pathlib import Path

(
    baseline_path,
    shadow_path,
    capacity_path,
    output_path,
    baseline_seconds,
    shadow_seconds,
    raw_start,
    raw_end,
    db_start,
    db_end,
    free_start,
    http_429_count,
) = sys.argv[1:]


def read_samples(path):
    with Path(path).open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def nearest_rank_p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def snapshot_p95(rows):
    mtimes = []
    for row in rows:
        value = int(row["snapshotMtime"])
        if not mtimes or value != mtimes[-1]:
            mtimes.append(value)
    return nearest_rank_p95([right - left for left, right in zip(mtimes, mtimes[1:])])


def terminal_snapshot_age(rows):
    if not rows:
        return None
    age = int(rows[-1]["sampledAt"]) - int(rows[-1]["snapshotMtime"])
    return age if age >= 0 else None


def network_delta(rows):
    if len(rows) < 2:
        return 0
    return max(0, int(rows[-1]["hostRxBytes"]) - int(rows[0]["hostRxBytes"])) + max(
        0, int(rows[-1]["hostTxBytes"]) - int(rows[0]["hostTxBytes"])
    )


def number_summary(rows, key):
    values = [float(row[key]) for row in rows]
    return {
        "average": statistics.fmean(values) if values else 0,
        "maximum": max(values, default=0),
    }


baseline = read_samples(baseline_path)
shadow = read_samples(shadow_path)
capacity = json.loads(Path(capacity_path).read_text(encoding="utf-8"))
baseline_p95 = snapshot_p95(baseline)
shadow_p95 = snapshot_p95(shadow)
baseline_terminal_age = terminal_snapshot_age(baseline)
shadow_terminal_age = terminal_snapshot_age(shadow)
snapshot_interval_limit = None if baseline_p95 in (None, 0) else baseline_p95 * 1.2
snapshot_ratio = (
    None
    if baseline_p95 in (None, 0) or shadow_p95 is None
    else shadow_p95 / baseline_p95
)
terminal_snapshot_fresh = (
    snapshot_interval_limit is not None
    and baseline_terminal_age is not None
    and shadow_terminal_age is not None
    and baseline_terminal_age <= snapshot_interval_limit
    and shadow_terminal_age <= snapshot_interval_limit
)
all_rows = baseline + shadow
nrestarts_zero = bool(all_rows) and all(int(row["nRestarts"]) == 0 for row in all_rows)
duckdb_single = (
    bool(all_rows)
    and all(int(row["duckdbOpeners"]) <= 1 for row in all_rows)
    and any(int(row["duckdbOpeners"]) == 1 for row in all_rows)
)
baseline_network_rate = network_delta(baseline) / max(1, int(baseline_seconds))
shadow_network = network_delta(shadow)
host_residual_network = max(
    0,
    shadow_network - round(baseline_network_rate * int(shadow_seconds)),
)

raw_growth = max(0, int(raw_end) - int(raw_start))
raw_gb_per_day = (
    raw_growth * 86_400 / max(1, int(shadow_seconds)) * 1.25 / 1_000_000_000
)
parquet_gb_per_day = float(capacity["projectedParquetGbPerDay"])
required_gb = 7 * raw_gb_per_day + 365 * parquet_gb_per_day + 30
available_limit_gb = 0.75 * int(free_start) / 1_000_000_000
capacity_pass = bool(capacity["projectionComplete"]) and required_gb <= available_limit_gb
existing_impact_pass = (
    snapshot_ratio is not None
    and snapshot_ratio <= 1.2
    and terminal_snapshot_fresh
    and nrestarts_zero
    and duckdb_single
)

report = {
    "schemaVersion": 1,
    "status": "pass" if capacity_pass and existing_impact_pass and int(http_429_count) == 0 else "hold",
    "measurement": {
        "baselineSeconds": int(baseline_seconds),
        "shadowSeconds": int(shadow_seconds),
        "snapshotMtimeIntervalP95BaselineSeconds": baseline_p95,
        "snapshotMtimeIntervalP95ShadowSeconds": shadow_p95,
        "snapshotP95Ratio": snapshot_ratio,
        "baselineTerminalSnapshotAgeSeconds": baseline_terminal_age,
        "shadowTerminalSnapshotAgeSeconds": shadow_terminal_age,
        "terminalSnapshotAgeLimitSeconds": snapshot_interval_limit,
        "terminalSnapshotFresh": terminal_snapshot_fresh,
        "nRestartsZero": nrestarts_zero,
        "duckdbSingleOpener": duckdb_single,
        "duckdbOpenerMinimum": min(
            (int(row["duckdbOpeners"]) for row in all_rows), default=0
        ),
        "duckdbOpenerMaximum": max(
            (int(row["duckdbOpeners"]) for row in all_rows), default=0
        ),
        "marketCpuPct": number_summary(shadow, "marketCpuPct"),
        "marketRssKb": number_summary(shadow, "marketRssKb"),
        "webCpuPct": number_summary(shadow, "webCpuPct"),
        "webRssKb": number_summary(shadow, "webRssKb"),
        "networkMethod": "host total is an upper bound; residual is not process-attributable",
        "hostNetworkUpperBoundBytes": shadow_network,
        "hostResidualNetworkEstimateBytes": host_residual_network,
        "databaseGrowthBytes": max(0, int(db_end) - int(db_start)),
        "rawRelationGrowthBytes": raw_growth,
        "http429Count": int(http_429_count),
    },
    "capacity": {
        "projectionComplete": capacity["projectionComplete"],
        "requiredMissingPartitions": capacity["requiredMissingPartitions"],
        "optionalEmptyPartitions": capacity["optionalEmptyPartitions"],
        "rawGbPerDay": raw_gb_per_day,
        "parquetGbPerDay": parquet_gb_per_day,
        "requiredGb": required_gb,
        "available75PercentGb": available_limit_gb,
        "pass": capacity_pass,
    },
    "existingRuntimeImpactPass": existing_impact_pass,
    "manualEvidenceRequired": ["AC-03", "AC-04", "AC-05", "AC-07", "AC-09"],
}
Path(output_path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

cp "$state_root/artifacts/service-state.json" "$evidence_dir/service-state.json"
git -C "$repo_root" status --short >"$evidence_dir/git-status-after.txt"
if ! cmp -s "$evidence_dir/git-status-before.txt" "$evidence_dir/git-status-after.txt"; then
  printf 'repository changed during isolated shadow; evidence retained for review\n' >&2
  exit 1
fi
source_digest_after="$(workspace_source_digest)"
printf '%s\n' "$source_digest_after" >"$evidence_dir/source-digest-after.txt"
if [[ "$source_digest_before" != "$source_digest_after" ]]; then
  printf 'source changed during isolated shadow; evidence retained for review\n' >&2
  exit 1
fi
printf 'evidenceDir=%s\nsummary=%s\n' "$evidence_dir" "$evidence_dir/summary.json"
printf 'manualReview=AC-03,AC-04,AC-05,AC-07,AC-09 database-summary.tsv and logs\n'
summary_status="$(/usr/bin/python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["status"])' \
  "$evidence_dir/summary.json")"
if [[ "$summary_status" != "pass" ]]; then
  printf 'shadow gate is HOLD; inspect summary and do not cut over\n' >&2
  exit 1
fi
