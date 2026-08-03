#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/migrate-state-dir.sh \
    --target "$HOME/.local/share/prep-watchdeck" \
    --archive-dir "$HOME/watchdeck-local-archive/state-YYYYMMDD-HHMMSS" \
    [--source PATH] \
    [--repo-root PATH]

The command copies active state to the target, archives the complete old state,
verifies both copies, and leaves every source file in place.
EOF
}

absolute_path() {
  realpath -m -- "$1"
}

directory_has_files() {
  [[ -d "$1" && -n "$(find "$1" -mindepth 1 -print -quit)" ]]
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

require_outside_repo() {
  local repo_root="$1"
  local path="$2"
  local label="$3"

  case "$path/" in
    "$repo_root/"*)
      echo "${label} must be outside the repository: ${path}" >&2
      return 2
      ;;
  esac
}

active_manifest() {
  local root="$1"
  local output="$2"
  local item=""

  {
    for item in watchdeck.duckdb watchdeck.duckdb.wal; do
      if [[ -f "$root/$item" ]]; then
        printf "%s\n" "$item"
      fi
    done

    for item in \
      snapshots \
      past-notes \
      dashboard-view-settings \
      usage-events \
      ops; do
      if [[ -d "$root/$item" ]]; then
        find "$root/$item" -type f -printf "${item}/%P\n"
      fi
    done
  } | LC_ALL=C sort >"$output"
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
    hash="$(sha256sum "$root/$relative_path" | awk '{print $1}')"
    printf "%s  %s\n" "$hash" "$relative_path" >>"$output"
  done <"$files"
}

assert_watchdeck_stopped() {
  local repo_root="$1"
  local processes=""
  local process_dir=""
  local process_cwd=""
  local process_command=""
  local process_id=""
  if [[ "${PREP_WATCHDECK_MIGRATION_SKIP_PROCESS_CHECK:-}" == "1" ]]; then
    echo "warning: process check skipped by explicit test-only override" >&2
    return
  fi

  processes="$(
    pgrep -af \
      'watchdeck (service|scan|publish-service)|scripts/start-all\.sh|scripts/update-live\.sh' \
      || true
  )"
  for process_dir in /proc/[0-9]*; do
    process_cwd="$(readlink "$process_dir/cwd" 2>/dev/null || true)"
    case "$process_cwd/" in
      "$repo_root/apps/web/"*)
        ;;
      *)
        continue
        ;;
    esac
    process_command="$(tr '\0' ' ' <"$process_dir/cmdline" 2>/dev/null || true)"
    case "$process_command" in
      *vite* | *svelte-kit* | *"bun run dev"* | *"bun run preview"*)
        process_id="${process_dir##*/}"
        processes+="${processes:+$'\n'}${process_id} ${process_command}"
        ;;
    esac
  done
  if [[ -n "$processes" ]]; then
    echo "watchdeck processes must be stopped before copying state:" >&2
    echo "$processes" >&2
    return 2
  fi
}

REPO_ROOT="$DEFAULT_REPO_ROOT"
SOURCE=""
TARGET="${PREP_WATCHDECK_STATE_DIR:-}"
ARCHIVE_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
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

REPO_ROOT="$(absolute_path "$REPO_ROOT")"
SOURCE="$(absolute_path "${SOURCE:-$REPO_ROOT/var}")"
if [[ -z "$TARGET" || -z "$ARCHIVE_DIR" ]]; then
  usage >&2
  exit 2
fi
TARGET="$(absolute_path "$TARGET")"
ARCHIVE_DIR="$(absolute_path "$ARCHIVE_DIR")"

if [[ ! -d "$SOURCE" ]]; then
  echo "state source does not exist: $SOURCE" >&2
  exit 2
fi
if paths_overlap "$SOURCE" "$TARGET" \
  || paths_overlap "$SOURCE" "$ARCHIVE_DIR" \
  || paths_overlap "$TARGET" "$ARCHIVE_DIR"; then
  echo "source, state target, and archive must not overlap" >&2
  exit 2
fi
require_outside_repo "$REPO_ROOT" "$TARGET" "state target"
require_outside_repo "$REPO_ROOT" "$ARCHIVE_DIR" "archive directory"

if directory_has_files "$TARGET"; then
  echo "state target must not already contain files: $TARGET" >&2
  exit 2
fi
if directory_has_files "$ARCHIVE_DIR"; then
  echo "archive directory must not already contain files: $ARCHIVE_DIR" >&2
  exit 2
fi

assert_watchdeck_stopped "$REPO_ROOT"
command -v rsync >/dev/null || {
  echo "rsync is required" >&2
  exit 2
}
command -v jq >/dev/null || {
  echo "jq is required" >&2
  exit 2
}

mkdir -p "$TARGET" "$ARCHIVE_DIR/state/var"

TMP_DIR="$(mktemp -d -t prep-watchdeck-migrate-state.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

(
  cd "$SOURCE"
  find . -type f -printf "%P\n" | LC_ALL=C sort
) >"$TMP_DIR/source-all-files"
active_manifest "$SOURCE" "$TMP_DIR/source-active-files"

if [[ ! -s "$TMP_DIR/source-active-files" ]]; then
  echo "state source has no active files to migrate: $SOURCE" >&2
  exit 2
fi

echo "== archive complete old state =="
rsync --archive "$SOURCE/" "$ARCHIVE_DIR/state/var/"

LEGACY_DB="$REPO_ROOT/data/scanner.duckdb"
if [[ -f "$LEGACY_DB" ]]; then
  echo "== archive legacy scanner database =="
  mkdir -p "$ARCHIVE_DIR/legacy-data"
  rsync --archive "$LEGACY_DB" "$ARCHIVE_DIR/legacy-data/scanner.duckdb"
  LEGACY_HASH="$(sha256sum "$LEGACY_DB" | awk '{print $1}')"
  ARCHIVED_LEGACY_HASH="$(
    sha256sum "$ARCHIVE_DIR/legacy-data/scanner.duckdb" | awk '{print $1}'
  )"
  if [[ "$LEGACY_HASH" != "$ARCHIVED_LEGACY_HASH" ]]; then
    echo "legacy scanner database archive hash mismatch" >&2
    exit 2
  fi
  printf "%s  scanner.duckdb\n" "$LEGACY_HASH" >"$ARCHIVE_DIR/LEGACY_DATA_SHA256"
fi

echo "== copy active state =="
rsync \
  --archive \
  --files-from="$TMP_DIR/source-active-files" \
  "$SOURCE/" \
  "$TARGET/"
mkdir -p "$TARGET/tmp/e2e" "$TARGET/tmp/performance" "$TARGET/tmp/soak"

hash_manifest \
  "$SOURCE" \
  "$TMP_DIR/source-active-files" \
  "$ARCHIVE_DIR/SOURCE_ACTIVE_SHA256"
hash_manifest \
  "$SOURCE" \
  "$TMP_DIR/source-all-files" \
  "$ARCHIVE_DIR/SOURCE_ALL_SHA256"
cp "$TMP_DIR/source-active-files" "$ARCHIVE_DIR/SOURCE_ACTIVE_MANIFEST.txt"
cp "$TMP_DIR/source-all-files" "$ARCHIVE_DIR/SOURCE_ALL_MANIFEST.txt"
printf "2\n" >"$ARCHIVE_DIR/STATE_LAYOUT_VERSION"

echo "== verify copied state =="
bash "$SCRIPT_DIR/verify-state-dir.sh" \
  --source "$SOURCE" \
  --target "$TARGET" \
  --archive-dir "$ARCHIVE_DIR" \
  --mode copy

cat >"$ARCHIVE_DIR/STATE_COPY_VERIFIED" <<EOF
verifiedAt=$(date --iso-8601=seconds)
source=$SOURCE
target=$TARGET
archive=$ARCHIVE_DIR
layoutVersion=2
source files remain in place
EOF

printf "sourceBytes=%s\n" "$(du -sb "$SOURCE" | awk '{print $1}')"
printf "targetBytes=%s\n" "$(du -sb "$TARGET" | awk '{print $1}')"
printf "archiveBytes=%s\n" "$(du -sb "$ARCHIVE_DIR" | awk '{print $1}')"
printf "next=export PREP_WATCHDECK_STATE_DIR=%q\n" "$TARGET"
echo "copy complete; do not remove the old source until cutover verification passes"
