#!/usr/bin/env bash

_watchdeck_absolute_path() {
  local base_dir="$1"
  local value="$2"

  if [[ "$value" = /* ]]; then
    realpath -m -- "$value"
  else
    realpath -m -- "$base_dir/$value"
  fi
}

_watchdeck_paths_disagree() {
  local label="$1"
  local first="$2"
  local second="$3"

  if [[ "$first" != "$second" ]]; then
    echo "${label} disagree: ${first} != ${second}" >&2
    return 2
  fi
}

resolve_watchdeck_state_paths() {
  local retired_override=""
  for retired_override in \
    PREP_WATCHDECK_TRADE_MEMOS_DIR \
    TRADE_MEMOS_DIR \
    PREP_WATCHDECK_ATTACK_TICKETS_DIR \
    ATTACK_TICKETS_DIR; do
    if [[ -v "$retired_override" ]]; then
      echo "retired record state override is no longer supported: $retired_override" >&2
      return 2
    fi
  done

  local repo_root
  repo_root="$(_watchdeck_absolute_path "$PWD" "$1")"
  local scanner_root="$repo_root/apps/scanner-core"
  local web_root="$repo_root/apps/web"

  WATCHDECK_STATE_DIR="$(
    _watchdeck_absolute_path \
      "$repo_root" \
      "${PREP_WATCHDECK_STATE_DIR:-$repo_root/var}"
  )"

  local scanner_out_dir
  local web_snapshot_path=""
  if [[ -n "${PREP_WATCHDECK_OUT_DIR:-}" ]]; then
    scanner_out_dir="$(
      _watchdeck_absolute_path "$scanner_root" "$PREP_WATCHDECK_OUT_DIR"
    )"
  elif [[ -n "${SCANNER_SNAPSHOT_PATH:-}" ]]; then
    web_snapshot_path="$(
      _watchdeck_absolute_path "$web_root" "$SCANNER_SNAPSHOT_PATH"
    )"
    if [[ "$(basename "$web_snapshot_path")" != "latest.json" ]]; then
      echo "SCANNER_SNAPSHOT_PATH must end with latest.json to bridge scanner output" >&2
      return 2
    fi
    scanner_out_dir="$(dirname "$web_snapshot_path")"
  else
    scanner_out_dir="$WATCHDECK_STATE_DIR/snapshots"
  fi

  WATCHDECK_SNAPSHOT_PATH="$scanner_out_dir/latest.json"
  if [[ -n "${SCANNER_SNAPSHOT_PATH:-}" ]]; then
    if [[ -z "$web_snapshot_path" ]]; then
      web_snapshot_path="$(
        _watchdeck_absolute_path "$web_root" "$SCANNER_SNAPSHOT_PATH"
      )"
    fi
    _watchdeck_paths_disagree \
      "scanner and Web snapshot paths" \
      "$WATCHDECK_SNAPSHOT_PATH" \
      "$web_snapshot_path" || return
  fi

  WATCHDECK_DATABASE_PATH="$(
    _watchdeck_absolute_path \
      "$scanner_root" \
      "${PREP_WATCHDECK_CACHE_DB_PATH:-$WATCHDECK_STATE_DIR/watchdeck.duckdb}"
  )"

  local scanner_service_path=""
  local web_service_path=""
  if [[ -n "${PREP_WATCHDECK_SERVICE_STATE_PATH:-}" ]]; then
    scanner_service_path="$(
      _watchdeck_absolute_path "$scanner_root" "$PREP_WATCHDECK_SERVICE_STATE_PATH"
    )"
  fi
  if [[ -n "${SCANNER_SERVICE_STATE_PATH:-}" ]]; then
    web_service_path="$(
      _watchdeck_absolute_path "$web_root" "$SCANNER_SERVICE_STATE_PATH"
    )"
  fi
  if [[ -n "$scanner_service_path" && -n "$web_service_path" ]]; then
    _watchdeck_paths_disagree \
      "scanner and Web service-state paths" \
      "$scanner_service_path" \
      "$web_service_path" || return
  fi
  WATCHDECK_SERVICE_STATE_PATH="$(
    printf "%s" \
      "${scanner_service_path:-${web_service_path:-$scanner_out_dir/service-state.json}}"
  )"

  local scanner_ticker_path=""
  local web_ticker_path=""
  if [[ -n "${PREP_WATCHDECK_TICKER_RUNTIME_PATH:-}" ]]; then
    scanner_ticker_path="$(
      _watchdeck_absolute_path "$scanner_root" "$PREP_WATCHDECK_TICKER_RUNTIME_PATH"
    )"
  fi
  if [[ -n "${SCANNER_TICKER_RUNTIME_PATH:-}" ]]; then
    web_ticker_path="$(
      _watchdeck_absolute_path "$web_root" "$SCANNER_TICKER_RUNTIME_PATH"
    )"
  fi
  if [[ -n "$scanner_ticker_path" && -n "$web_ticker_path" ]]; then
    _watchdeck_paths_disagree \
      "scanner and Web ticker-runtime paths" \
      "$scanner_ticker_path" \
      "$web_ticker_path" || return
  fi
  WATCHDECK_TICKER_RUNTIME_PATH="$(
    printf "%s" \
      "${scanner_ticker_path:-${web_ticker_path:-$scanner_out_dir/ticker-runtime.json}}"
  )"

  WATCHDECK_CHART_DIR="$scanner_out_dir/charts/latest"
  if [[ -n "${SCANNER_CHARTS_DIR:-}" ]]; then
    local web_chart_dir
    web_chart_dir="$(
      _watchdeck_absolute_path "$web_root" "$SCANNER_CHARTS_DIR"
    )"
    _watchdeck_paths_disagree \
      "scanner and Web chart paths" \
      "$WATCHDECK_CHART_DIR" \
      "$web_chart_dir" || return
  fi

  if [[ -n "${PREP_WATCHDECK_PAST_NOTES_DIR:-}" ]]; then
    WATCHDECK_PAST_NOTES_DIR="$(
      _watchdeck_absolute_path "$scanner_root" "$PREP_WATCHDECK_PAST_NOTES_DIR"
    )"
  else
    WATCHDECK_PAST_NOTES_DIR="$(
      _watchdeck_absolute_path "$web_root" "${PAST_NOTES_DIR:-$WATCHDECK_STATE_DIR/past-notes}"
    )"
  fi
  if [[ -n "${PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR:-}" ]]; then
    WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR="$(
      _watchdeck_absolute_path \
        "$scanner_root" \
        "$PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR"
    )"
  else
    WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR="$WATCHDECK_STATE_DIR/dashboard-view-settings"
  fi

  export WATCHDECK_STATE_DIR
  export WATCHDECK_SNAPSHOT_PATH
  export WATCHDECK_DATABASE_PATH
  export WATCHDECK_SERVICE_STATE_PATH
  export WATCHDECK_TICKER_RUNTIME_PATH
  export WATCHDECK_CHART_DIR
  export WATCHDECK_PAST_NOTES_DIR
  export WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR

  export PREP_WATCHDECK_STATE_DIR="$WATCHDECK_STATE_DIR"
  export PREP_WATCHDECK_DATA_DIR="$WATCHDECK_STATE_DIR"
  export PREP_WATCHDECK_OUT_DIR="$scanner_out_dir"
  export PREP_WATCHDECK_CACHE_DB_PATH="$WATCHDECK_DATABASE_PATH"
  export PREP_WATCHDECK_PAST_NOTES_DIR="$WATCHDECK_PAST_NOTES_DIR"
  export PREP_WATCHDECK_LOCK_FILE="$WATCHDECK_STATE_DIR/scanner.lock"
  export PREP_WATCHDECK_SERVICE_STATE_PATH="$WATCHDECK_SERVICE_STATE_PATH"
  export PREP_WATCHDECK_TICKER_RUNTIME_PATH="$WATCHDECK_TICKER_RUNTIME_PATH"
  export PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR="$WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR"

  export SCANNER_SNAPSHOT_PATH="$WATCHDECK_SNAPSHOT_PATH"
  export SCANNER_SERVICE_STATE_PATH="$WATCHDECK_SERVICE_STATE_PATH"
  export SCANNER_TICKER_RUNTIME_PATH="$WATCHDECK_TICKER_RUNTIME_PATH"
  export SCANNER_CHARTS_DIR="$WATCHDECK_CHART_DIR"
  export PAST_NOTES_DIR="$WATCHDECK_PAST_NOTES_DIR"
}

print_watchdeck_state_paths() {
  printf "stateDir=%s\n" "$WATCHDECK_STATE_DIR"
  printf "snapshotPath=%s\n" "$WATCHDECK_SNAPSHOT_PATH"
  printf "databasePath=%s\n" "$WATCHDECK_DATABASE_PATH"
  printf "serviceStatePath=%s\n" "$WATCHDECK_SERVICE_STATE_PATH"
  printf "tickerRuntimePath=%s\n" "$WATCHDECK_TICKER_RUNTIME_PATH"
  printf "chartDir=%s\n" "$WATCHDECK_CHART_DIR"
}
