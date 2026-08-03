#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/verify-repo-history-archive.sh \
    --archive-dir /absolute/path/to/archive \
    [--repo-root /path/to/prep-watchdeck]

Re-verifies the tracked history manifest, current source hashes, and archived
copy immediately before historical documents are removed from the worktree.
EOF
}

history_manifest() {
  local repo_root="$1"
  local output="$2"

  cd "$repo_root"
  while IFS= read -r -d '' path; do
    case "$path" in
      docs/README.md | docs/current/* | docs/decisions/* | docs/plans/active/* | docs/action-required.md)
        continue
        ;;
      docs/* | mockups/*)
        printf '%s\n' "$path"
        ;;
    esac
  done < <(git ls-files -z -- docs mockups) | LC_ALL=C sort >"$output"
}

hash_manifest() {
  local root="$1"
  local manifest="$2"
  local output="$3"
  local path=""
  local hash=""

  : >"$output"
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    if [[ ! -f "$root/$path" ]]; then
      echo "archive manifest file is missing: $root/$path" >&2
      return 2
    fi
    hash="$(sha256sum "$root/$path" | awk '{print $1}')"
    printf "%s  %s\n" "$hash" "$path" >>"$output"
  done <"$manifest"
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
if [[ ! -d "$ARCHIVE_DIR" ]]; then
  echo "archive directory does not exist: $ARCHIVE_DIR" >&2
  exit 2
fi

MANIFEST="$ARCHIVE_DIR/MANIFEST.txt"
RECORDED_HASHES="$ARCHIVE_DIR/SHA256SUMS"
VERIFIED="$ARCHIVE_DIR/VERIFIED"
for required in "$MANIFEST" "$RECORDED_HASHES" "$VERIFIED"; do
  if [[ ! -f "$required" ]]; then
    echo "archive verification evidence is missing: $required" >&2
    exit 2
  fi
done

TMP_DIR="$(mktemp -d -t prep-watchdeck-verify-repo-archive.XXXXXX)"
cleanup() {
  rm -r -- "$TMP_DIR"
}
trap cleanup EXIT

history_manifest "$REPO_ROOT" "$TMP_DIR/expected-manifest"
if ! cmp -s "$TMP_DIR/expected-manifest" "$MANIFEST"; then
  echo "archive manifest no longer matches tracked historical documents" >&2
  diff -u "$MANIFEST" "$TMP_DIR/expected-manifest" >&2 || true
  exit 2
fi

expected_count="$(wc -l <"$MANIFEST")"
recorded_count="$(awk -F= '$1 == "file_count" { print $2 }' "$VERIFIED")"
if [[ "$recorded_count" != "$expected_count" ]]; then
  echo "archive VERIFIED file_count does not match MANIFEST" >&2
  exit 2
fi

hash_manifest "$REPO_ROOT" "$MANIFEST" "$TMP_DIR/source-hashes"
if ! cmp -s "$RECORDED_HASHES" "$TMP_DIR/source-hashes"; then
  echo "source historical documents changed after archive; do not remove them" >&2
  diff -u "$RECORDED_HASHES" "$TMP_DIR/source-hashes" >&2 || true
  exit 2
fi

hash_manifest "$ARCHIVE_DIR" "$MANIFEST" "$TMP_DIR/archive-hashes"
if ! cmp -s "$RECORDED_HASHES" "$TMP_DIR/archive-hashes"; then
  echo "archive files do not match recorded hashes" >&2
  diff -u "$RECORDED_HASHES" "$TMP_DIR/archive-hashes" >&2 || true
  exit 2
fi

echo "repo history archive verification passed"
echo "archiveDir=$ARCHIVE_DIR"
echo "fileCount=$expected_count"
echo "source and archive hashes match recorded evidence"
