#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/archive-retired-records.sh \
    --archive-dir /absolute/repo-external/path \
    [--repo-root /path/to/prep-watchdeck]

Copies Trade Memo and Attack Ticket files to a verified Repo-external archive.
Source files are never removed. Stop all watchdeck writers before running it.
EOF
}

absolute_from() {
  local base="$1"
  local value="$2"
  if [[ "$value" = /* ]]; then
    realpath -m -- "$value"
  else
    realpath -m -- "$base/$value"
  fi
}

directory_has_files() {
  [[ -d "$1" && -n "$(find "$1" -mindepth 1 -print -quit)" ]]
}

paths_overlap() {
  local first="$1"
  local second="$2"
  case "$first/" in
    "$second/"*) return 0 ;;
  esac
  case "$second/" in
    "$first/"*) return 0 ;;
  esac
  return 1
}

require_outside_repo() {
  local repo_root="$1"
  local path="$2"
  case "$path/" in
    "$repo_root/"*)
      echo "archive directory must be outside the repository: $path" >&2
      return 2
      ;;
  esac
}

resolve_record_dir() {
  local scanner_root="$1"
  local web_root="$2"
  local state_dir="$3"
  local prefixed_name="$4"
  local legacy_name="$5"
  local default_name="$6"
  local prefixed_value="${!prefixed_name:-}"
  local legacy_value="${!legacy_name:-}"

  if [[ -n "$prefixed_value" ]]; then
    absolute_from "$scanner_root" "$prefixed_value"
  elif [[ -n "$legacy_value" ]]; then
    absolute_from "$web_root" "$legacy_value"
  else
    absolute_from "$state_dir" "$default_name"
  fi
}

assert_watchdeck_stopped() {
  local repo_root="$1"
  local process_dir=""
  local process_cwd=""
  local process_command=""
  local found=false

  for process_dir in /proc/[0-9]*; do
    process_cwd="$(readlink "$process_dir/cwd" 2>/dev/null || true)"
    case "$process_cwd/" in
      "$repo_root/"*) ;;
      *) continue ;;
    esac
    process_command="$(tr '\0' ' ' <"$process_dir/cmdline" 2>/dev/null || true)"
    case "$process_command" in
      *"watchdeck service"* | *"watchdeck scan"* | *"watchdeck publish-service"* | \
        *"scripts/start-all.sh"* | *"scripts/update-live.sh"* | *"bun run dev"* | \
        *"bun run preview"* | *vite* | *svelte-kit*)
        found=true
        ;;
    esac
  done

  if [[ "$found" == true ]]; then
    echo "watchdeck writers must be stopped before archiving retired records" >&2
    return 2
  fi
}

classify_source() {
  local root="$1"
  local archive_prefix="$2"
  local data_output="$3"
  local ignored_output="$4"
  local unsafe_output="$5"
  local path=""
  local relative_path=""
  local basename=""

  : >"$data_output"
  : >"$ignored_output"
  : >"$unsafe_output"
  [[ -d "$root" ]] || return 0

  while IFS= read -r -d '' path; do
    relative_path="${path#"$root/"}"
    if [[ "$relative_path" == *$'\n'* || "$relative_path" == *$'\t'* ]]; then
      echo "retired record paths must not contain tabs or newlines" >&2
      return 2
    fi
    basename="${relative_path##*/}"
    case "$basename" in
      .gitkeep)
        printf "%s\t%s\n" "$archive_prefix/$relative_path" "tracked-placeholder" \
          >>"$ignored_output"
        ;;
      *.lock | *.tmp)
        printf "%s\n" "$archive_prefix/$relative_path" >>"$unsafe_output"
        ;;
      *)
        printf "%s\n" "$relative_path" >>"$data_output"
        ;;
    esac
  done < <(find "$root" -type f -print0)

  LC_ALL=C sort -o "$data_output" "$data_output"
  LC_ALL=C sort -o "$ignored_output" "$ignored_output"
  LC_ALL=C sort -o "$unsafe_output" "$unsafe_output"
}

validate_current_json() {
  local root="$1"
  local key="$2"
  local label="$3"
  local status_output="$4"
  local count_output="$5"
  local current="$root/current.json"

  if [[ ! -f "$current" ]]; then
    printf "missing" >"$status_output"
    printf "0" >"$count_output"
    return
  fi
  if ! jq -e . "$current" >/dev/null 2>&1; then
    echo "$label current.json is not valid JSON" >&2
    return 2
  fi
  if ! jq -e --arg key "$key" 'type == "object" and (.[$key] | type == "array")' \
    "$current" >/dev/null; then
    echo "$label current.json must contain a $key array" >&2
    return 2
  fi
  printf "valid" >"$status_output"
  jq -r --arg key "$key" '.[$key] | length' "$current" >"$count_output"
}

build_file_entries() {
  local source_root="$1"
  local archive_prefix="$2"
  local files="$3"
  local output="$4"
  local relative_path=""
  local hash=""
  local bytes=""

  : >"$output"
  while IFS= read -r relative_path; do
    [[ -n "$relative_path" ]] || continue
    hash="$(sha256sum "$source_root/$relative_path" | awk '{print $1}')"
    bytes="$(stat -c '%s' "$source_root/$relative_path")"
    printf "%s\t%s\t%s/%s\n" "$hash" "$bytes" "$archive_prefix" "$relative_path" \
      >>"$output"
  done <"$files"
}

REPO_ROOT="$DEFAULT_REPO_ROOT"
ARCHIVE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
    --archive-dir)
      ARCHIVE_DIR="${2:-}"
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

if [[ -z "$ARCHIVE_DIR" ]]; then
  usage >&2
  exit 2
fi

REPO_ROOT="$(realpath -m -- "$REPO_ROOT")"
ARCHIVE_DIR="$(realpath -m -- "$ARCHIVE_DIR")"
SCANNER_ROOT="$REPO_ROOT/apps/scanner-core"
WEB_ROOT="$REPO_ROOT/apps/web"
STATE_DIR="$(absolute_from "$REPO_ROOT" "${PREP_WATCHDECK_STATE_DIR:-var}")"
TRADE_MEMOS_DIR="$(
  resolve_record_dir \
    "$SCANNER_ROOT" \
    "$WEB_ROOT" \
    "$STATE_DIR" \
    PREP_WATCHDECK_TRADE_MEMOS_DIR \
    TRADE_MEMOS_DIR \
    trade-memos
)"
ATTACK_TICKETS_DIR="$(
  resolve_record_dir \
    "$SCANNER_ROOT" \
    "$WEB_ROOT" \
    "$STATE_DIR" \
    PREP_WATCHDECK_ATTACK_TICKETS_DIR \
    ATTACK_TICKETS_DIR \
    attack-tickets
)"

git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  echo "repository root is not a Git worktree: $REPO_ROOT" >&2
  exit 2
}
require_outside_repo "$REPO_ROOT" "$ARCHIVE_DIR"
if directory_has_files "$ARCHIVE_DIR"; then
  echo "archive directory must not already contain files: $ARCHIVE_DIR" >&2
  exit 2
fi
if paths_overlap "$ARCHIVE_DIR" "$TRADE_MEMOS_DIR" || \
  paths_overlap "$ARCHIVE_DIR" "$ATTACK_TICKETS_DIR"; then
  echo "archive directory and retired record sources must not overlap" >&2
  exit 2
fi
if paths_overlap "$TRADE_MEMOS_DIR" "$ATTACK_TICKETS_DIR"; then
  echo "trade memo and attack ticket source directories must not overlap" >&2
  exit 2
fi

assert_watchdeck_stopped "$REPO_ROOT"
for command_name in jq rsync sha256sum stat; do
  command -v "$command_name" >/dev/null || {
    echo "$command_name is required" >&2
    exit 2
  }
done

mkdir -p "$ARCHIVE_DIR"
TMP_DIR="$(mktemp -d -t prep-watchdeck-retired-records.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

classify_source \
  "$TRADE_MEMOS_DIR" \
  trade-memos \
  "$TMP_DIR/trade-files" \
  "$TMP_DIR/trade-ignored" \
  "$TMP_DIR/trade-unsafe"
classify_source \
  "$ATTACK_TICKETS_DIR" \
  attack-tickets \
  "$TMP_DIR/attack-files" \
  "$TMP_DIR/attack-ignored" \
  "$TMP_DIR/attack-unsafe"
cat "$TMP_DIR/trade-unsafe" "$TMP_DIR/attack-unsafe" >"$TMP_DIR/unsafe"
if [[ -s "$TMP_DIR/unsafe" ]]; then
  echo "lock or temporary files exist in retired record state; stop all writers and inspect them" >&2
  exit 2
fi

validate_current_json \
  "$TRADE_MEMOS_DIR" memos "trade memos" "$TMP_DIR/trade-status" "$TMP_DIR/trade-count"
validate_current_json \
  "$ATTACK_TICKETS_DIR" tickets "attack tickets" "$TMP_DIR/attack-status" "$TMP_DIR/attack-count"

build_file_entries \
  "$TRADE_MEMOS_DIR" trade-memos "$TMP_DIR/trade-files" "$TMP_DIR/trade-before"
build_file_entries \
  "$ATTACK_TICKETS_DIR" attack-tickets "$TMP_DIR/attack-files" "$TMP_DIR/attack-before"
cat "$TMP_DIR/trade-before" "$TMP_DIR/attack-before" | LC_ALL=C sort -t $'\t' -k3,3 \
  >"$TMP_DIR/files-before"
cat "$TMP_DIR/trade-ignored" "$TMP_DIR/attack-ignored" | LC_ALL=C sort \
  >"$TMP_DIR/ignored"

TOTAL_BYTES="$(awk -F '\t' '{ total += $2 } END { print total + 0 }' "$TMP_DIR/files-before")"
AVAILABLE_BYTES="$(df -PB1 "$ARCHIVE_DIR" | awk 'NR == 2 { print $4 }')"
if [[ -z "$AVAILABLE_BYTES" ]] || (( AVAILABLE_BYTES < TOTAL_BYTES )); then
  echo "archive directory has insufficient free space" >&2
  exit 2
fi

mkdir -p \
  "$ARCHIVE_DIR/retired-state/trade-memos" \
  "$ARCHIVE_DIR/retired-state/attack-tickets"
if [[ -s "$TMP_DIR/trade-files" ]]; then
  rsync \
    --archive \
    --files-from="$TMP_DIR/trade-files" \
    "$TRADE_MEMOS_DIR/" \
    "$ARCHIVE_DIR/retired-state/trade-memos/"
fi
if [[ -s "$TMP_DIR/attack-files" ]]; then
  rsync \
    --archive \
    --files-from="$TMP_DIR/attack-files" \
    "$ATTACK_TICKETS_DIR/" \
    "$ARCHIVE_DIR/retired-state/attack-tickets/"
fi

classify_source \
  "$TRADE_MEMOS_DIR" \
  trade-memos \
  "$TMP_DIR/trade-files-after" \
  "$TMP_DIR/trade-ignored-after" \
  "$TMP_DIR/trade-unsafe-after"
classify_source \
  "$ATTACK_TICKETS_DIR" \
  attack-tickets \
  "$TMP_DIR/attack-files-after" \
  "$TMP_DIR/attack-ignored-after" \
  "$TMP_DIR/attack-unsafe-after"
build_file_entries \
  "$TRADE_MEMOS_DIR" trade-memos "$TMP_DIR/trade-files-after" "$TMP_DIR/trade-after"
build_file_entries \
  "$ATTACK_TICKETS_DIR" attack-tickets "$TMP_DIR/attack-files-after" "$TMP_DIR/attack-after"
cat "$TMP_DIR/trade-after" "$TMP_DIR/attack-after" | LC_ALL=C sort -t $'\t' -k3,3 \
  >"$TMP_DIR/files-after"
cat "$TMP_DIR/trade-ignored-after" "$TMP_DIR/attack-ignored-after" | LC_ALL=C sort \
  >"$TMP_DIR/ignored-after"
cat "$TMP_DIR/trade-unsafe-after" "$TMP_DIR/attack-unsafe-after" >"$TMP_DIR/unsafe-after"
if [[ -s "$TMP_DIR/unsafe-after" ]] || \
  ! cmp -s "$TMP_DIR/files-before" "$TMP_DIR/files-after" || \
  ! cmp -s "$TMP_DIR/ignored" "$TMP_DIR/ignored-after"; then
  echo "retired record source changed during archive copy" >&2
  exit 2
fi

awk -F '\t' '{ print $1 "  " $3 }' "$TMP_DIR/files-before" >"$ARCHIVE_DIR/FILES_SHA256"
FILES_JSON="$(
  jq -Rn \
    '[inputs | split("\t") | {sha256: .[0], bytes: (.[1] | tonumber), path: .[2]}]' \
    <"$TMP_DIR/files-before"
)"
IGNORED_JSON="$(
  jq -Rn \
    '[inputs | split("\t") | {path: .[0], reason: .[1]}]' \
    <"$TMP_DIR/ignored"
)"
BASELINE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
CREATED_AT="$(date --iso-8601=seconds)"
TRADE_EXISTS=false
ATTACK_EXISTS=false
if [[ -d "$TRADE_MEMOS_DIR" ]]; then
  TRADE_EXISTS=true
fi
if [[ -d "$ATTACK_TICKETS_DIR" ]]; then
  ATTACK_EXISTS=true
fi
TRADE_FILE_COUNT="$(wc -l <"$TMP_DIR/trade-files" | tr -d ' ')"
ATTACK_FILE_COUNT="$(wc -l <"$TMP_DIR/attack-files" | tr -d ' ')"
TRADE_BYTES="$(awk -F '\t' '$3 ~ /^trade-memos\// { total += $2 } END { print total + 0 }' "$TMP_DIR/files-before")"
ATTACK_BYTES="$(awk -F '\t' '$3 ~ /^attack-tickets\// { total += $2 } END { print total + 0 }' "$TMP_DIR/files-before")"

jq -n \
  --arg kind "prep-watchdeck-retired-records-archive" \
  --arg createdAt "$CREATED_AT" \
  --arg baselineCommit "$BASELINE_COMMIT" \
  --arg repoRoot "$REPO_ROOT" \
  --arg tradePath "$TRADE_MEMOS_DIR" \
  --arg attackPath "$ATTACK_TICKETS_DIR" \
  --arg tradeStatus "$(<"$TMP_DIR/trade-status")" \
  --arg attackStatus "$(<"$TMP_DIR/attack-status")" \
  --argjson tradeExists "$TRADE_EXISTS" \
  --argjson attackExists "$ATTACK_EXISTS" \
  --argjson tradeCount "$(<"$TMP_DIR/trade-count")" \
  --argjson attackCount "$(<"$TMP_DIR/attack-count")" \
  --argjson tradeFileCount "$TRADE_FILE_COUNT" \
  --argjson attackFileCount "$ATTACK_FILE_COUNT" \
  --argjson tradeBytes "$TRADE_BYTES" \
  --argjson attackBytes "$ATTACK_BYTES" \
  --argjson files "$FILES_JSON" \
  --argjson ignored "$IGNORED_JSON" \
  '{
    schemaVersion: 1,
    kind: $kind,
    createdAt: $createdAt,
    baselineCommit: $baselineCommit,
    repoRoot: $repoRoot,
    sources: {
      tradeMemos: {
        path: $tradePath,
        exists: $tradeExists,
        fileCount: $tradeFileCount,
        totalBytes: $tradeBytes,
        currentJson: {status: $tradeStatus, rawRecordCount: $tradeCount}
      },
      attackTickets: {
        path: $attackPath,
        exists: $attackExists,
        fileCount: $attackFileCount,
        totalBytes: $attackBytes,
        currentJson: {status: $attackStatus, rawRecordCount: $attackCount}
      }
    },
    files: $files,
    ignored: $ignored,
    restoreSmoke: {verified: false, fileCount: 0}
  }' >"$ARCHIVE_DIR/manifest.json"

bash "$SCRIPT_DIR/verify-retired-records-archive.sh" --archive-dir "$ARCHIVE_DIR"

printf "archive=%s\n" "$ARCHIVE_DIR"
printf "fileCount=%s\n" "$((TRADE_FILE_COUNT + ATTACK_FILE_COUNT))"
printf "tradeMemoRawCount=%s\n" "$(<"$TMP_DIR/trade-count")"
printf "attackTicketRawCount=%s\n" "$(<"$TMP_DIR/attack-count")"
echo "source files remain in place"
