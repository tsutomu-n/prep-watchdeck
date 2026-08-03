#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/verify-state-dir.sh \
    --source PATH \
    --target PATH \
    --archive-dir PATH \
    [--mode copy|cutover]

Modes:
  copy     Require source, target, and archived copies to have identical hashes.
  cutover  Require the old source to remain unchanged and validate the live target.
EOF
}

absolute_path() {
  realpath -m -- "$1"
}

paths_overlap() {
  local first="${1%/}"
  local second="${2%/}"

  case "$first/" in
    "$second/"*) return 0 ;;
  esac
  case "$second/" in
    "$first/"*) return 0 ;;
  esac
  return 1
}

active_manifest() {
  local root="$1"
  local output="$2"
  local layout_version="$3"
  local item=""
  local -a active_directories=(
    snapshots
    past-notes
    dashboard-view-settings
    usage-events
    ops
  )

  if [[ "$layout_version" == "1" ]]; then
    active_directories+=(trade-memos attack-tickets)
  fi

  {
    for item in watchdeck.duckdb watchdeck.duckdb.wal; do
      if [[ -f "$root/$item" ]]; then
        printf "%s\n" "$item"
      fi
    done

    for item in "${active_directories[@]}"; do
      if [[ -d "$root/$item" ]]; then
        find "$root/$item" -type f -printf "${item}/%P\n"
      fi
    done
  } | LC_ALL=C sort >"$output"
}

read_layout_version() {
  local archive_dir="$1"
  local marker="$archive_dir/STATE_LAYOUT_VERSION"
  local marker_bytes=""
  local marker_value=""

  if [[ ! -e "$marker" ]]; then
    printf "1\n"
    return
  fi
  if [[ ! -f "$marker" ]]; then
    echo "unsupported state layout version: marker is not a regular file" >&2
    return 2
  fi

  marker_bytes="$(stat -c '%s' "$marker")"
  marker_value="$(cat "$marker")"
  if [[ "$marker_bytes" != "2" || "$marker_value" != "2" ]]; then
    echo "unsupported state layout version: ${marker_value:-empty}" >&2
    return 2
  fi
  printf "2\n"
}

target_contains_retired_records() {
  local target="$1"
  local directory=""

  for directory in trade-memos attack-tickets; do
    if [[ -d "$target/$directory" ]] \
      && [[ -n "$(find "$target/$directory" -type f -print -quit)" ]]; then
      return 0
    fi
  done
  return 1
}

all_manifest() {
  local root="$1"
  local output="$2"
  (
    cd "$root"
    find . -type f -printf "%P\n" | LC_ALL=C sort
  ) >"$output"
}

hash_manifest() {
  local root="$1"
  local files="$2"
  local output="$3"
  local relative_path=""
  local hash=""

  : >"$output"
  while IFS= read -r relative_path; do
    [[ -n "$relative_path" ]] || continue
    if [[ ! -f "$root/$relative_path" ]]; then
      echo "missing file during state verification: $root/$relative_path" >&2
      return 2
    fi
    hash="$(sha256sum "$root/$relative_path" | awk '{print $1}')"
    printf "%s  %s\n" "$hash" "$relative_path" >>"$output"
  done <"$files"
}

require_empty_or_json_file() {
  local path="$1"
  local label="$2"

  if [[ -f "$path" ]] && ! jq -e . "$path" >/dev/null; then
    echo "${label} is not valid JSON: ${path}" >&2
    return 2
  fi
}

validate_target_structure() {
  local target="$1"
  local layout_version="$2"
  local snapshot="$target/snapshots/latest.json"
  local chart_dir="$target/snapshots/charts/latest"
  local run_id=""
  local chart=""
  local chart_run_id=""

  if [[ ! -f "$target/watchdeck.duckdb" ]]; then
    echo "target database is missing: $target/watchdeck.duckdb" >&2
    return 2
  fi
  if [[ ! -s "$snapshot" ]]; then
    echo "target snapshot is missing or empty: $snapshot" >&2
    return 2
  fi
  run_id="$(jq -er '.runId | strings | select(length > 0)' "$snapshot")" || {
    echo "latest snapshot has no valid runId: $snapshot" >&2
    return 2
  }
  jq -e '.rows | arrays' "$snapshot" >/dev/null || {
    echo "latest snapshot has no rows array: $snapshot" >&2
    return 2
  }

  if [[ -d "$chart_dir" ]]; then
    while IFS= read -r chart; do
      chart_run_id="$(jq -er '.snapshotRunId | strings | select(length > 0)' "$chart")" || {
        echo "chart has no valid snapshotRunId: $chart" >&2
        return 2
      }
      if [[ "$chart_run_id" != "$run_id" ]]; then
        echo "snapshotRunId does not match latest snapshot: $chart" >&2
        return 2
      fi
    done < <(find "$chart_dir" -maxdepth 1 -type f -name '*.json' | LC_ALL=C sort)
  fi

  require_empty_or_json_file "$target/snapshots/service-state.json" "service state"
  require_empty_or_json_file "$target/snapshots/ticker-runtime.json" "ticker runtime"
  require_empty_or_json_file "$target/past-notes/current.json" "past notes"
  if [[ "$layout_version" == "1" ]]; then
    require_empty_or_json_file "$target/trade-memos/current.json" "trade memos"
    require_empty_or_json_file "$target/attack-tickets/current.json" "attack tickets"
  fi
  require_empty_or_json_file \
    "$target/dashboard-view-settings/current.json" \
    "dashboard view settings"

  printf "snapshotRunId=%s\n" "$run_id"
  printf "databaseBytes=%s\n" "$(stat -c '%s' "$target/watchdeck.duckdb")"
  print_record_count "$target/past-notes/current.json" "pastNotes" ".notes"
  if [[ "$layout_version" == "1" ]]; then
    print_record_count "$target/trade-memos/current.json" "tradeMemos" ".memos"
    print_record_count "$target/attack-tickets/current.json" "attackTickets" ".tickets"
  fi
  print_record_count \
    "$target/dashboard-view-settings/current.json" \
    "dashboardViewSettings" \
    ".views | objects | keys"
}

print_record_count() {
  local path="$1"
  local label="$2"
  local selector="$3"

  if [[ -f "$path" ]]; then
    printf "%s=%s\n" "$label" "$(jq -er "${selector} | arrays | length" "$path")"
  else
    printf "%s=missing\n" "$label"
  fi
}

require_count_not_decreased() {
  local source_path="$1"
  local target_path="$2"
  local label="$3"
  local selector="$4"
  local source_count=""
  local target_count=""

  if [[ ! -f "$source_path" ]]; then
    return
  fi
  if [[ ! -f "$target_path" ]]; then
    echo "${label} file disappeared after cutover: ${target_path}" >&2
    return 2
  fi

  source_count="$(jq -er "$selector" "$source_path")" || {
    echo "source ${label} count is unreadable: ${source_path}" >&2
    return 2
  }
  target_count="$(jq -er "$selector" "$target_path")" || {
    echo "target ${label} count is unreadable: ${target_path}" >&2
    return 2
  }
  if (( target_count < source_count )); then
    echo "${label} record count decreased: ${source_count} -> ${target_count}" >&2
    return 2
  fi
}

SOURCE=""
TARGET=""
ARCHIVE_DIR=""
MODE="copy"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE="${2:-}"
      shift 2
      ;;
    --target)
      TARGET="${2:-}"
      shift 2
      ;;
    --archive-dir)
      ARCHIVE_DIR="${2:-}"
      shift 2
      ;;
    --mode)
      MODE="${2:-}"
      shift 2
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$SOURCE" || -z "$TARGET" || -z "$ARCHIVE_DIR" ]]; then
  usage >&2
  exit 2
fi
if [[ "$MODE" != "copy" && "$MODE" != "cutover" ]]; then
  echo "--mode must be copy or cutover" >&2
  exit 2
fi

SOURCE="$(absolute_path "$SOURCE")"
TARGET="$(absolute_path "$TARGET")"
ARCHIVE_DIR="$(absolute_path "$ARCHIVE_DIR")"
ARCHIVED_SOURCE="$ARCHIVE_DIR/state/var"
BASELINE_ACTIVE="$ARCHIVE_DIR/SOURCE_ACTIVE_SHA256"
BASELINE_ALL="$ARCHIVE_DIR/SOURCE_ALL_SHA256"
BASELINE_ACTIVE_MANIFEST="$ARCHIVE_DIR/SOURCE_ACTIVE_MANIFEST.txt"
BASELINE_ALL_MANIFEST="$ARCHIVE_DIR/SOURCE_ALL_MANIFEST.txt"

if [[ ! -d "$SOURCE" || ! -d "$TARGET" || ! -d "$ARCHIVED_SOURCE" ]]; then
  echo "source, target, and archived source directories must exist" >&2
  exit 2
fi
if paths_overlap "$SOURCE" "$TARGET" \
  || paths_overlap "$SOURCE" "$ARCHIVE_DIR" \
  || paths_overlap "$TARGET" "$ARCHIVE_DIR"; then
  echo "source, state target, and archive must not overlap" >&2
  exit 2
fi
if [[ ! -f "$BASELINE_ACTIVE" \
  || ! -f "$BASELINE_ALL" \
  || ! -f "$BASELINE_ACTIVE_MANIFEST" \
  || ! -f "$BASELINE_ALL_MANIFEST" ]]; then
  echo "archive verification manifests are missing" >&2
  exit 2
fi
LAYOUT_VERSION="$(read_layout_version "$ARCHIVE_DIR")" || exit 2

TMP_DIR="$(mktemp -d -t prep-watchdeck-verify-state.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

all_manifest "$SOURCE" "$TMP_DIR/source-all-files"
if ! cmp -s "$BASELINE_ALL_MANIFEST" "$TMP_DIR/source-all-files"; then
  echo "old source state changed after migration; stop cutover" >&2
  diff -u "$BASELINE_ALL_MANIFEST" "$TMP_DIR/source-all-files" >&2 || true
  exit 2
fi
hash_manifest "$SOURCE" "$BASELINE_ALL_MANIFEST" "$TMP_DIR/source-all-sha256"
if ! cmp -s "$BASELINE_ALL" "$TMP_DIR/source-all-sha256"; then
  echo "old source state changed after migration; stop cutover" >&2
  diff -u "$BASELINE_ALL" "$TMP_DIR/source-all-sha256" >&2 || true
  exit 2
fi

all_manifest "$ARCHIVED_SOURCE" "$TMP_DIR/archive-all-files"
if ! cmp -s "$BASELINE_ALL_MANIFEST" "$TMP_DIR/archive-all-files"; then
  echo "archived state file list does not match recorded source manifest" >&2
  diff -u "$BASELINE_ALL_MANIFEST" "$TMP_DIR/archive-all-files" >&2 || true
  exit 2
fi
hash_manifest "$ARCHIVED_SOURCE" "$BASELINE_ALL_MANIFEST" "$TMP_DIR/archive-all-sha256"
if ! cmp -s "$BASELINE_ALL" "$TMP_DIR/archive-all-sha256"; then
  echo "archived state does not match recorded hashes" >&2
  diff -u "$BASELINE_ALL" "$TMP_DIR/archive-all-sha256" >&2 || true
  exit 2
fi

active_manifest "$SOURCE" "$TMP_DIR/source-active-files" "$LAYOUT_VERSION"
if ! cmp -s "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/source-active-files"; then
  echo "old source active file list changed after migration; stop cutover" >&2
  diff -u "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/source-active-files" >&2 || true
  exit 2
fi
hash_manifest "$SOURCE" "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/source-active-sha256"
if ! cmp -s "$BASELINE_ACTIVE" "$TMP_DIR/source-active-sha256"; then
  echo "old source state changed after migration; stop cutover" >&2
  diff -u "$BASELINE_ACTIVE" "$TMP_DIR/source-active-sha256" >&2 || true
  exit 2
fi

if [[ "$LAYOUT_VERSION" == "2" ]] && target_contains_retired_records "$TARGET"; then
  echo "v2 target contains retired record files" >&2
  exit 2
fi

if [[ "$MODE" == "copy" ]]; then
  active_manifest "$TARGET" "$TMP_DIR/target-active-files" "$LAYOUT_VERSION"
  if ! cmp -s "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/target-active-files"; then
    echo "state target active file list does not match source" >&2
    diff -u "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/target-active-files" >&2 || true
    exit 2
  fi
  hash_manifest "$TARGET" "$BASELINE_ACTIVE_MANIFEST" "$TMP_DIR/target-active-sha256"
  if ! cmp -s "$BASELINE_ACTIVE" "$TMP_DIR/target-active-sha256"; then
    echo "state target hashes do not match source" >&2
    diff -u "$BASELINE_ACTIVE" "$TMP_DIR/target-active-sha256" >&2 || true
    exit 2
  fi
else
  while IFS= read -r active_file; do
    [[ -n "$active_file" ]] || continue
    if [[ ! -f "$TARGET/$active_file" ]]; then
      echo "live state lost a migrated file: $TARGET/$active_file" >&2
      exit 2
    fi
  done <"$BASELINE_ACTIVE_MANIFEST"

  require_count_not_decreased \
    "$SOURCE/past-notes/current.json" \
    "$TARGET/past-notes/current.json" \
    "past notes" \
    '.notes | arrays | length'
  if [[ "$LAYOUT_VERSION" == "1" ]]; then
    require_count_not_decreased \
      "$SOURCE/trade-memos/current.json" \
      "$TARGET/trade-memos/current.json" \
      "trade memos" \
      '.memos | arrays | length'
    require_count_not_decreased \
      "$SOURCE/attack-tickets/current.json" \
      "$TARGET/attack-tickets/current.json" \
      "attack tickets" \
      '.tickets | arrays | length'
  fi
  require_count_not_decreased \
    "$SOURCE/dashboard-view-settings/current.json" \
    "$TARGET/dashboard-view-settings/current.json" \
    "dashboard view settings" \
    '.views | objects | keys | length'
fi

validate_target_structure "$TARGET" "$LAYOUT_VERSION"
printf "layoutVersion=%s\n" "$LAYOUT_VERSION"
printf "mode=%s\n" "$MODE"
printf "source=%s\n" "$SOURCE"
printf "target=%s\n" "$TARGET"
printf "archive=%s\n" "$ARCHIVE_DIR"
printf "verification=passed\n"
