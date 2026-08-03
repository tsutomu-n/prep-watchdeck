#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/resolve-state-paths.sh"
source "$ROOT_DIR/scripts/lib/select-web-port.sh"
resolve_watchdeck_state_paths "$ROOT_DIR"

REQUESTED_PORT="${PORT:-5173}"
PORT="$(select_watchdeck_web_port "$REQUESTED_PORT")"
SNAPSHOT_SOURCE="${SNAPSHOT_SOURCE:-live}"
SNAPSHOT_FALLBACK_SOURCE="${SNAPSHOT_FALLBACK_SOURCE:-cache}"
START_ALL_STRICT_SNAPSHOT="${START_ALL_STRICT_SNAPSHOT:-false}"
FIXTURE_SET="${FIXTURE_SET:-basic}"
LIVE_MAX_SYMBOLS="${LIVE_MAX_SYMBOLS:-30}"
TEMPLATE="${TEMPLATE:-balanced}"
LATEST_SNAPSHOT_PATH="$WATCHDECK_SNAPSHOT_PATH"
EFFECTIVE_SNAPSHOT_SOURCE="$SNAPSHOT_SOURCE"
SNAPSHOT_LOG_PATH="$(mktemp -t prep-watchdeck-start-all.XXXXXX)"

cleanup_start_all() {
  rm -f "$SNAPSHOT_LOG_PATH"
}
trap cleanup_start_all EXIT

echo "== prep-watchdeck start all =="
echo "source=${SNAPSHOT_SOURCE} fallback=${SNAPSHOT_FALLBACK_SOURCE} template=${TEMPLATE} port=${PORT}"
print_watchdeck_state_paths

is_truthy() {
  case "$1" in
    1 | true | TRUE | yes | YES | on | ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_snapshot_source() {
  case "$1" in
    live | fixture | cache | skip)
      return 0
      ;;
    *)
      echo "Unknown SNAPSHOT_SOURCE: $1" >&2
      echo "Use one of: live, fixture, cache, skip" >&2
      exit 2
      ;;
  esac
}

validate_fallback_source() {
  case "$1" in
    cache | skip | fixture | none)
      return 0
      ;;
    *)
      echo "Unknown SNAPSHOT_FALLBACK_SOURCE: $1" >&2
      echo "Use one of: cache, skip, fixture, none" >&2
      exit 2
      ;;
  esac
}

snapshot_exists() {
  [[ -s "$LATEST_SNAPSHOT_PATH" ]]
}

run_logged() {
  : >"$SNAPSHOT_LOG_PATH"
  set +e
  "$@" 2>&1 | tee "$SNAPSHOT_LOG_PATH"
  local status="${PIPESTATUS[0]}"
  set -e
  return "$status"
}

last_snapshot_failure_is_duckdb_lock() {
  grep -Eiq "(DuckDB cache is locked|Could not set lock on file|Conflicting lock|cache locked)" \
    "$SNAPSHOT_LOG_PATH" &&
    grep -Eiq "(DuckDB|watchdeck\\.duckdb)" "$SNAPSHOT_LOG_PATH"
}

last_snapshot_failure_is_source_unavailable() {
  grep -Eiq "(source unavailable|No such file|cache.*empty|no cached snapshot|not found)" \
    "$SNAPSHOT_LOG_PATH"
}

print_snapshot_failure_hint() {
  local source="$1"
  if last_snapshot_failure_is_duckdb_lock; then
    echo "hint: ${source} failed because DuckDB is locked by another watchdeck process." >&2
    echo "hint: wait for the running scan/service to finish, or start web only with SNAPSHOT_SOURCE=skip." >&2
    if command -v pgrep >/dev/null 2>&1; then
      local processes
      processes="$(pgrep -af "watchdeck (service|scan|publish-service)|uv run watchdeck|scripts/start-all.sh" || true)"
      if [[ -n "$processes" ]]; then
        echo "hint: related processes:" >&2
        echo "$processes" >&2
      fi
    fi
    return
  fi

  if last_snapshot_failure_is_source_unavailable; then
    echo "hint: ${source} could not provide a snapshot. Check fixture name, cache contents, or existing latest.json." >&2
  fi
}

run_snapshot_source() {
  local source="$1"
  cd "$ROOT_DIR/apps/scanner-core"
  case "$source" in
    live)
      echo "== backend: scanner-core live snapshot =="
      run_logged env PREP_WATCHDECK_LIVE_MAX_SYMBOLS="$LIVE_MAX_SYMBOLS" \
        uv run watchdeck scan --source live --template "$TEMPLATE"
      ;;
    fixture)
      echo "== backend: scanner-core fixture snapshot =="
      run_logged uv run watchdeck scan --source fixture --fixture-set "$FIXTURE_SET" --template "$TEMPLATE"
      ;;
    cache)
      echo "== backend: scanner-core cache snapshot =="
      run_logged uv run watchdeck scan --source cache --template "$TEMPLATE"
      ;;
    skip)
      : >"$SNAPSHOT_LOG_PATH"
      echo "== backend: skip snapshot update =="
      ;;
  esac
}

use_existing_snapshot_fallback() {
  if snapshot_exists; then
    echo "== backend fallback: use existing latest snapshot =="
    echo "warning: using ${LATEST_SNAPSHOT_PATH} without updating it" >&2
    EFFECTIVE_SNAPSHOT_SOURCE="existing"
    return 0
  fi
  return 1
}

run_snapshot_with_fallback() {
  local initial_status=0
  run_snapshot_source "$SNAPSHOT_SOURCE" || initial_status=$?
  if [[ "$initial_status" -eq 0 ]]; then
    EFFECTIVE_SNAPSHOT_SOURCE="$SNAPSHOT_SOURCE"
    return
  fi

  echo "warning: ${SNAPSHOT_SOURCE} snapshot failed with exit ${initial_status}" >&2
  local initial_failure_is_duckdb_lock=false
  if last_snapshot_failure_is_duckdb_lock; then
    initial_failure_is_duckdb_lock=true
  fi
  print_snapshot_failure_hint "$SNAPSHOT_SOURCE"

  if is_truthy "$START_ALL_STRICT_SNAPSHOT"; then
    echo "strict snapshot mode is enabled; aborting before web startup" >&2
    exit "$initial_status"
  fi

  case "$SNAPSHOT_SOURCE" in
    fixture | skip)
      exit "$initial_status"
      ;;
  esac

  case "$SNAPSHOT_FALLBACK_SOURCE" in
    cache)
      if [[ "$SNAPSHOT_SOURCE" != "cache" ]]; then
        if [[ "$initial_failure_is_duckdb_lock" == true ]]; then
          echo "warning: cache fallback uses the same DuckDB; skipping it after a lock failure" >&2
        elif run_snapshot_source cache; then
          EFFECTIVE_SNAPSHOT_SOURCE="cache"
          return
        else
          echo "warning: cache fallback failed" >&2
          print_snapshot_failure_hint "cache fallback"
        fi
      fi
      if use_existing_snapshot_fallback; then
        return
      fi
      ;;
    skip)
      if use_existing_snapshot_fallback; then
        return
      fi
      ;;
    fixture)
      if run_snapshot_source fixture; then
        EFFECTIVE_SNAPSHOT_SOURCE="fixture"
        return
      fi
      echo "warning: fixture fallback failed" >&2
      print_snapshot_failure_hint "fixture fallback"
      ;;
    none)
      ;;
  esac

  echo "snapshot fallback failed; web server was not started" >&2
  exit "$initial_status"
}

validate_snapshot_source "$SNAPSHOT_SOURCE"
validate_fallback_source "$SNAPSHOT_FALLBACK_SOURCE"
run_snapshot_with_fallback

echo "== frontend: prepare generated types =="
cd "$ROOT_DIR/apps/web"
bun run generate:types

echo "== frontend: start web =="
echo "url=http://127.0.0.1:${PORT}/"
echo "source=${EFFECTIVE_SNAPSHOT_SOURCE} requested_source=${SNAPSHOT_SOURCE} template=${TEMPLATE} live_max_symbols=${LIVE_MAX_SYMBOLS}"

PREP_WATCHDECK_LIVE_TEMPLATE="$TEMPLATE" \
  PREP_WATCHDECK_LIVE_MAX_SYMBOLS="$LIVE_MAX_SYMBOLS" \
  PREP_WATCHDECK_RUNTIME_TARGET=local \
  PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS=true \
  bun run dev -- --port "$PORT" --strictPort
