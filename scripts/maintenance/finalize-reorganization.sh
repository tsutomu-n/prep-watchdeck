#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/maintenance/finalize-reorganization.sh \
    --repo-history-archive /absolute/path/to/repo-history-archive \
    --state-target /absolute/path/to/live-state \
    --state-archive-dir /absolute/path/to/state-archive \
    [--repo-root /path/to/prep-watchdeck] \
    [--apply]

Without --apply, verifies every prerequisite and prints the exact removal plan.
With --apply, removes only files listed in the verified Repo history manifest
and the verified legacy data/scanner.duckdb. The old var/ state is retained for
rollback and is never removed by this command. Before removal, --apply must
prepare writable finalization evidence inside the Repo history archive.
EOF
}

absolute_path() {
  realpath -m -- "$1"
}

verify_legacy_database_archive() {
  local repo_root="$1"
  local state_archive="$2"
  local source_db="$repo_root/data/scanner.duckdb"
  local archived_db="$state_archive/legacy-data/scanner.duckdb"
  local hash_file="$state_archive/LEGACY_DATA_SHA256"
  local expected_hash=""
  local source_hash=""
  local archived_hash=""

  if [[ ! -f "$source_db" ]]; then
    return
  fi
  if [[ ! -f "$archived_db" || ! -f "$hash_file" ]]; then
    echo "legacy database archive evidence is missing" >&2
    return 2
  fi

  expected_hash="$(awk '$2 == "scanner.duckdb" { print $1 }' "$hash_file")"
  source_hash="$(sha256sum "$source_db" | awk '{print $1}')"
  archived_hash="$(sha256sum "$archived_db" | awk '{print $1}')"
  if [[ -z "$expected_hash" || "$source_hash" != "$expected_hash" ]]; then
    echo "legacy source database no longer matches archived evidence" >&2
    return 2
  fi
  if [[ "$archived_hash" != "$expected_hash" ]]; then
    echo "archived legacy database no longer matches recorded evidence" >&2
    return 2
  fi
}

validate_removal_manifest() {
  local manifest="$1"
  local path=""

  if [[ ! -s "$manifest" ]]; then
    echo "Repo history manifest is empty" >&2
    return 2
  fi
  while IFS= read -r path; do
    case "$path" in
      docs/README.md | docs/current/* | docs/decisions/* | docs/plans/active/* | docs/action-required.md)
        echo "manifest contains a retained current document: $path" >&2
        return 2
        ;;
      docs/* | mockups/*)
        ;;
      *)
        echo "manifest contains a path outside docs history or mockups: $path" >&2
        return 2
        ;;
    esac
  done <"$manifest"
}

REPO_ROOT=""
REPO_HISTORY_ARCHIVE=""
STATE_TARGET=""
STATE_ARCHIVE_DIR=""
APPLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
    --repo-history-archive)
      REPO_HISTORY_ARCHIVE="${2:-}"
      shift 2
      ;;
    --state-target)
      STATE_TARGET="${2:-}"
      shift 2
      ;;
    --state-archive-dir)
      STATE_ARCHIVE_DIR="${2:-}"
      shift 2
      ;;
    --apply)
      APPLY=true
      shift
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
if [[ -z "$REPO_HISTORY_ARCHIVE" || -z "$STATE_TARGET" || -z "$STATE_ARCHIVE_DIR" ]]; then
  usage >&2
  exit 2
fi

REPO_ROOT="$(absolute_path "$REPO_ROOT")"
REPO_HISTORY_ARCHIVE="$(absolute_path "$REPO_HISTORY_ARCHIVE")"
STATE_TARGET="$(absolute_path "$STATE_TARGET")"
STATE_ARCHIVE_DIR="$(absolute_path "$STATE_ARCHIVE_DIR")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="$REPO_HISTORY_ARCHIVE/MANIFEST.txt"

echo "== verify Repo history archive =="
bash "$SCRIPT_DIR/verify-repo-history-archive.sh" \
  --repo-root "$REPO_ROOT" \
  --archive-dir "$REPO_HISTORY_ARCHIVE"
validate_removal_manifest "$MANIFEST"

echo "== verify state cutover =="
bash "$SCRIPT_DIR/verify-state-dir.sh" \
  --source "$REPO_ROOT/var" \
  --target "$STATE_TARGET" \
  --archive-dir "$STATE_ARCHIVE_DIR" \
  --mode cutover

echo "== verify legacy database archive =="
verify_legacy_database_archive "$REPO_ROOT" "$STATE_ARCHIVE_DIR"

REMOVAL_COUNT="$(wc -l <"$MANIFEST")"
LEGACY_DATABASE=false
if [[ -f "$REPO_ROOT/data/scanner.duckdb" ]]; then
  LEGACY_DATABASE=true
fi

echo "verification=passed"
echo "historicalFilesToRemove=$REMOVAL_COUNT"
echo "legacyDatabaseToRemove=$LEGACY_DATABASE"
echo "oldStateRetained=$REPO_ROOT/var"

if [[ "$APPLY" != true ]]; then
  echo "dry-run only; re-run with --apply to remove verified historical files"
  exit 0
fi

FINALIZATION_EVIDENCE="$REPO_HISTORY_ARCHIVE/REPO_FINALIZATION_VERIFIED"
FINALIZATION_EVIDENCE_TMP=""
FINALIZATION_REMOVAL_STARTED=false

cleanup_finalization_evidence() {
  if [[ -z "$FINALIZATION_EVIDENCE_TMP" || ! -e "$FINALIZATION_EVIDENCE_TMP" ]]; then
    return
  fi
  if [[ "$FINALIZATION_REMOVAL_STARTED" == true ]]; then
    echo "pending Repo finalization evidence retained: $FINALIZATION_EVIDENCE_TMP" >&2
    return
  fi
  rm -f -- "$FINALIZATION_EVIDENCE_TMP"
}
trap cleanup_finalization_evidence EXIT

if [[ -d "$FINALIZATION_EVIDENCE" ]]; then
  echo "cannot prepare Repo finalization evidence: target is a directory" >&2
  exit 2
fi
if ! FINALIZATION_EVIDENCE_TMP="$(
  mktemp "$REPO_HISTORY_ARCHIVE/.REPO_FINALIZATION_VERIFIED.XXXXXX"
)"; then
  echo "cannot prepare Repo finalization evidence in $REPO_HISTORY_ARCHIVE" >&2
  exit 2
fi
if ! cat >"$FINALIZATION_EVIDENCE_TMP" <<EOF
preparedAt=$(date --iso-8601=seconds)
repoRoot=$REPO_ROOT
stateTarget=$STATE_TARGET
stateArchive=$STATE_ARCHIVE_DIR
historicalFilesPlanned=$REMOVAL_COUNT
legacyDatabasePlanned=$LEGACY_DATABASE
oldStateRetained=$REPO_ROOT/var
EOF
then
  echo "cannot prepare Repo finalization evidence in $REPO_HISTORY_ARCHIVE" >&2
  exit 2
fi
if ! chmod 0644 "$FINALIZATION_EVIDENCE_TMP"; then
  echo "cannot prepare Repo finalization evidence in $REPO_HISTORY_ARCHIVE" >&2
  exit 2
fi

FINALIZATION_REMOVAL_STARTED=true
echo "== remove verified historical files =="
while IFS= read -r path; do
  [[ -n "$path" ]] || continue
  rm -- "$REPO_ROOT/$path"
done <"$MANIFEST"

if [[ "$LEGACY_DATABASE" == true ]]; then
  rm -- "$REPO_ROOT/data/scanner.duckdb"
fi

if ! cat >>"$FINALIZATION_EVIDENCE_TMP" <<EOF
finalizedAt=$(date --iso-8601=seconds)
historicalFilesRemoved=$REMOVAL_COUNT
legacyDatabaseRemoved=$LEGACY_DATABASE
EOF
then
  echo "cannot complete Repo finalization evidence: $FINALIZATION_EVIDENCE_TMP" >&2
  exit 2
fi
if ! mv -fT -- "$FINALIZATION_EVIDENCE_TMP" "$FINALIZATION_EVIDENCE"; then
  echo "cannot publish Repo finalization evidence: $FINALIZATION_EVIDENCE_TMP" >&2
  exit 2
fi
FINALIZATION_EVIDENCE_TMP=""

echo "Repo reorganization finalization applied"
echo "historicalFilesRemoved=$REMOVAL_COUNT"
echo "legacyDatabaseRemoved=$LEGACY_DATABASE"
echo "old var/ retained for rollback"
echo "finalizationEvidence=$FINALIZATION_EVIDENCE"
