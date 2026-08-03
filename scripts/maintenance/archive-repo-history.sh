#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/archive-repo-history.sh \
    --archive-dir /absolute/path/to/new-empty-archive \
    [--repo-root /path/to/prep-watchdeck]

Copies tracked historical docs and mockups to an external archive, verifies
relative-path SHA-256 hashes, and leaves every source file in place.
EOF
}

REPO_ROOT=""
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
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi
if [[ -z "$ARCHIVE_DIR" ]]; then
  echo "--archive-dir is required" >&2
  exit 2
fi

REPO_ROOT="$(realpath "$REPO_ROOT")"
ARCHIVE_DIR="$(realpath -m "$ARCHIVE_DIR")"

if [[ ! -d "$REPO_ROOT/.git" ]]; then
  echo "repo root does not contain .git: $REPO_ROOT" >&2
  exit 2
fi

case "$ARCHIVE_DIR/" in
  "$REPO_ROOT/"*)
    echo "archive directory must be outside the repository" >&2
    exit 2
    ;;
esac

mkdir -p "$ARCHIVE_DIR"
if [[ -n "$(find "$ARCHIVE_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
  echo "archive directory must not already contain files" >&2
  exit 2
fi

TMP_DIR="$(mktemp -d -t prep-watchdeck-repo-archive.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

MANIFEST_TMP="$TMP_DIR/MANIFEST.txt"
SOURCE_HASHES="$TMP_DIR/source.sha256"
TARGET_HASHES="$TMP_DIR/target.sha256"

cd "$REPO_ROOT"
while IFS= read -r -d '' path; do
  case "$path" in
    docs/README.md | docs/current/* | docs/decisions/* | docs/plans/active/* | docs/action-required.md)
      continue
      ;;
    docs/* | mockups/*)
      printf '%s\n' "$path"
      ;;
  esac
done < <(git ls-files -z -- docs mockups) | LC_ALL=C sort >"$MANIFEST_TMP"

if [[ ! -s "$MANIFEST_TMP" ]]; then
  echo "no tracked historical docs or mockups found" >&2
  exit 3
fi

rsync \
  --archive \
  --relative \
  --files-from="$MANIFEST_TMP" \
  "$REPO_ROOT/" \
  "$ARCHIVE_DIR/"

while IFS= read -r path; do
  sha256sum "$path"
done <"$MANIFEST_TMP" >"$SOURCE_HASHES"

cd "$ARCHIVE_DIR"
while IFS= read -r path; do
  sha256sum "$path"
done <"$MANIFEST_TMP" >"$TARGET_HASHES"

if ! cmp -s "$SOURCE_HASHES" "$TARGET_HASHES"; then
  echo "archive hash verification failed" >&2
  diff -u "$SOURCE_HASHES" "$TARGET_HASHES" >&2 || true
  exit 4
fi

cp "$MANIFEST_TMP" "$ARCHIVE_DIR/MANIFEST.txt"
cp "$SOURCE_HASHES" "$ARCHIVE_DIR/SHA256SUMS"
cat >"$ARCHIVE_DIR/VERIFIED" <<EOF
verified_at=$(date --iso-8601=seconds)
repo_root=$REPO_ROOT
file_count=$(wc -l <"$MANIFEST_TMP")
source files remain in place
EOF

echo "repo history archive verified"
echo "archiveDir=$ARCHIVE_DIR"
echo "fileCount=$(wc -l <"$MANIFEST_TMP")"
echo "source files remain in place; no Git tracking was changed"
printf "beforeRemoval=bash scripts/maintenance/verify-repo-history-archive.sh --archive-dir %q\n" \
  "$ARCHIVE_DIR"
