#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/verify-retired-records-archive.sh \
    --archive-dir /absolute/path/to/retired-records-archive

Re-verifies archived bytes, manifest metadata, source stability, and a temporary
restore copy. It never removes source records.
EOF
}

classify_source() {
  local root="$1"
  local archive_prefix="$2"
  local output="$3"
  local ignored_output="$4"
  local path=""
  local relative_path=""
  local basename=""
  local hash=""
  local bytes=""

  : >"$output"
  : >"$ignored_output"
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
        echo "lock or temporary files exist in retired record source" >&2
        return 2
        ;;
      *)
        hash="$(sha256sum "$path" | awk '{print $1}')"
        bytes="$(stat -c '%s' "$path")"
        printf "%s\t%s\t%s/%s\n" "$hash" "$bytes" "$archive_prefix" "$relative_path" \
          >>"$output"
        ;;
    esac
  done < <(find "$root" -type f -print0)
  LC_ALL=C sort -t $'\t' -k3,3 -o "$output" "$output"
  LC_ALL=C sort -o "$ignored_output" "$ignored_output"
}

build_archive_entries() {
  local root="$1"
  local output="$2"
  local path=""
  local relative_path=""
  local hash=""
  local bytes=""

  : >"$output"
  while IFS= read -r -d '' path; do
    relative_path="${path#"$root/"}"
    if [[ "$relative_path" == *$'\n'* || "$relative_path" == *$'\t'* ]]; then
      echo "archive paths must not contain tabs or newlines" >&2
      return 2
    fi
    hash="$(sha256sum "$path" | awk '{print $1}')"
    bytes="$(stat -c '%s' "$path")"
    printf "%s\t%s\t%s\n" "$hash" "$bytes" "$relative_path" >>"$output"
  done < <(find "$root" -type f -print0)
  LC_ALL=C sort -t $'\t' -k3,3 -o "$output" "$output"
}

validate_archived_current() {
  local archive_root="$1"
  local source_name="$2"
  local directory="$3"
  local key="$4"
  local label="$5"
  local expected_status=""
  local expected_count=""
  local current="$archive_root/retired-state/$directory/current.json"

  expected_status="$(jq -er ".sources.${source_name}.currentJson.status" "$archive_root/manifest.json")"
  expected_count="$(
    jq -er ".sources.${source_name}.currentJson.rawRecordCount | numbers" \
      "$archive_root/manifest.json"
  )"
  if [[ "$expected_status" == "missing" ]]; then
    if [[ -f "$current" || "$expected_count" != "0" ]]; then
      echo "$label archived current.json status does not match manifest" >&2
      return 2
    fi
    return
  fi
  if [[ "$expected_status" != "valid" || ! -f "$current" ]]; then
    echo "$label archived current.json status does not match manifest" >&2
    return 2
  fi
  if ! jq -e --arg key "$key" 'type == "object" and (.[$key] | type == "array")' \
    "$current" >/dev/null 2>&1; then
    echo "$label archived current.json envelope is invalid" >&2
    return 2
  fi
  if [[ "$(jq -r --arg key "$key" '.[$key] | length' "$current")" != "$expected_count" ]]; then
    echo "$label archived raw record count does not match manifest" >&2
    return 2
  fi
}

ARCHIVE_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
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
ARCHIVE_DIR="$(realpath -m -- "$ARCHIVE_DIR")"
MANIFEST="$ARCHIVE_DIR/manifest.json"
HASH_FILE="$ARCHIVE_DIR/FILES_SHA256"
RETIRED_STATE="$ARCHIVE_DIR/retired-state"

for command_name in jq rsync sha256sum stat; do
  command -v "$command_name" >/dev/null || {
    echo "$command_name is required" >&2
    exit 2
  }
done
if [[ ! -f "$MANIFEST" || ! -f "$HASH_FILE" || ! -d "$RETIRED_STATE" ]]; then
  echo "retired record archive evidence is incomplete" >&2
  exit 2
fi
if ! jq -e '
  .schemaVersion == 1 and
  .kind == "prep-watchdeck-retired-records-archive" and
  (.files | type == "array") and
  (.ignored | type == "array")
' "$MANIFEST" >/dev/null; then
  echo "retired record archive manifest is invalid" >&2
  exit 2
fi

rm -f -- "$ARCHIVE_DIR/ARCHIVE_VERIFIED"
TMP_DIR="$(mktemp -d -t prep-watchdeck-verify-retired.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

jq -r '.files[] | [.sha256, (.bytes | tostring), .path] | @tsv' "$MANIFEST" \
  | LC_ALL=C sort -t $'\t' -k3,3 >"$TMP_DIR/manifest-files"
jq -r '.ignored[] | [.path, .reason] | @tsv' "$MANIFEST" | LC_ALL=C sort \
  >"$TMP_DIR/manifest-ignored"
build_archive_entries "$RETIRED_STATE" "$TMP_DIR/archive-files"
if ! cmp -s "$TMP_DIR/manifest-files" "$TMP_DIR/archive-files"; then
  echo "archive files do not match manifest" >&2
  exit 2
fi
awk -F '\t' '{ print $1 "  " $3 }' "$TMP_DIR/manifest-files" >"$TMP_DIR/expected-sha256"
if ! cmp -s "$HASH_FILE" "$TMP_DIR/expected-sha256"; then
  echo "FILES_SHA256 does not match manifest" >&2
  exit 2
fi

validate_archived_current "$ARCHIVE_DIR" tradeMemos trade-memos memos "trade memos"
validate_archived_current "$ARCHIVE_DIR" attackTickets attack-tickets tickets "attack tickets"

TRADE_SOURCE="$(jq -er '.sources.tradeMemos.path | strings' "$MANIFEST")"
ATTACK_SOURCE="$(jq -er '.sources.attackTickets.path | strings' "$MANIFEST")"
TRADE_EXPECTED_EXISTS="$(jq -r '.sources.tradeMemos.exists' "$MANIFEST")"
ATTACK_EXPECTED_EXISTS="$(jq -r '.sources.attackTickets.exists' "$MANIFEST")"
if [[ "$TRADE_EXPECTED_EXISTS" != "$([[ -d "$TRADE_SOURCE" ]] && echo true || echo false)" ]] || \
  [[ "$ATTACK_EXPECTED_EXISTS" != "$([[ -d "$ATTACK_SOURCE" ]] && echo true || echo false)" ]]; then
  echo "retired record source existence changed after archive" >&2
  exit 2
fi
classify_source \
  "$TRADE_SOURCE" trade-memos "$TMP_DIR/trade-source-files" "$TMP_DIR/trade-source-ignored"
classify_source \
  "$ATTACK_SOURCE" attack-tickets "$TMP_DIR/attack-source-files" "$TMP_DIR/attack-source-ignored"
cat "$TMP_DIR/trade-source-files" "$TMP_DIR/attack-source-files" \
  | LC_ALL=C sort -t $'\t' -k3,3 >"$TMP_DIR/source-files"
cat "$TMP_DIR/trade-source-ignored" "$TMP_DIR/attack-source-ignored" | LC_ALL=C sort \
  >"$TMP_DIR/source-ignored"
if ! cmp -s "$TMP_DIR/manifest-files" "$TMP_DIR/source-files" || \
  ! cmp -s "$TMP_DIR/manifest-ignored" "$TMP_DIR/source-ignored"; then
  echo "retired record source changed after archive" >&2
  exit 2
fi

RESTORE_ROOT="$TMP_DIR/restore"
mkdir -p "$RESTORE_ROOT"
rsync --archive "$RETIRED_STATE/" "$RESTORE_ROOT/"
build_archive_entries "$RESTORE_ROOT" "$TMP_DIR/restore-files"
if ! cmp -s "$TMP_DIR/manifest-files" "$TMP_DIR/restore-files"; then
  echo "retired record restore smoke does not match manifest" >&2
  exit 2
fi

FILE_COUNT="$(wc -l <"$TMP_DIR/manifest-files" | tr -d ' ')"
MANIFEST_TMP="$ARCHIVE_DIR/.manifest.json.$$.tmp"
jq --argjson fileCount "$FILE_COUNT" \
  '.restoreSmoke = {verified: true, fileCount: $fileCount}' \
  "$MANIFEST" >"$MANIFEST_TMP"
mv -fT -- "$MANIFEST_TMP" "$MANIFEST"
MANIFEST_HASH="$(sha256sum "$MANIFEST" | awk '{print $1}')"
HASH_LIST_HASH="$(sha256sum "$HASH_FILE" | awk '{print $1}')"
VERIFIED_TMP="$ARCHIVE_DIR/.ARCHIVE_VERIFIED.$$.tmp"
cat >"$VERIFIED_TMP" <<EOF
verifiedAt=$(date --iso-8601=seconds)
manifestSha256=$MANIFEST_HASH
filesSha256Sha256=$HASH_LIST_HASH
fileCount=$FILE_COUNT
source files remain in place
EOF
mv -fT -- "$VERIFIED_TMP" "$ARCHIVE_DIR/ARCHIVE_VERIFIED"

printf "archive=%s\n" "$ARCHIVE_DIR"
printf "fileCount=%s\n" "$FILE_COUNT"
echo "restoreSmoke=passed"
echo "verification=passed"
