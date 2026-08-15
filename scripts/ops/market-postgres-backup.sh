#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/deploy/market-postgres/compose.yaml"
PROJECT_NAME="prep-watchdeck-market"
EXPECTED_DATABASE="prep_watchdeck_market"

usage() {
  cat <<'EOF'
Usage:
  bash scripts/ops/market-postgres-backup.sh \
    --state-root /absolute/repo-external/state \
    --env-file /absolute/repo-external/postgres.env \
    --backup-dir /absolute/repo-external/backups

Creates one verified custom-format pg_dump using the dedicated market Compose project.
EOF
}

require_value() {
  if [[ $# -lt 2 || -z "$2" ]]; then
    printf 'missing value for %s\n' "$1" >&2
    usage >&2
    exit 2
  fi
}

require_absolute_path() {
  local label="$1"
  local value="$2"
  if [[ "$value" != /* || "$value" == *$'\n'* || "$value" == *$'\t'* ]]; then
    printf '%s must be an absolute single-line path: %s\n' "$label" "$value" >&2
    exit 2
  fi
}

require_outside_repo() {
  local label="$1"
  local value="$2"
  case "$value/" in
    "$REPO_ROOT/"*)
      printf '%s must be outside the repository: %s\n' "$label" "$value" >&2
      exit 2
      ;;
  esac
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

require_secure_env_file() {
  local path="$1"
  if [[ ! -f "$path" || -L "$path" || ! -O "$path" ]]; then
    printf 'env file must be a regular, non-symlink file owned by the current user: %s\n' \
      "$path" >&2
    exit 2
  fi
  if [[ "$(stat -c '%a' "$path")" != "600" ]]; then
    printf 'env file mode must be 0600: %s\n' "$path" >&2
    exit 2
  fi
}

STATE_ROOT=""
ENV_FILE=""
BACKUP_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-root)
      require_value "$@"
      STATE_ROOT="$2"
      shift 2
      ;;
    --env-file)
      require_value "$@"
      ENV_FILE="$2"
      shift 2
      ;;
    --backup-dir)
      require_value "$@"
      BACKUP_DIR="$2"
      shift 2
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$STATE_ROOT" || -z "$ENV_FILE" || -z "$BACKUP_DIR" ]]; then
  usage >&2
  exit 2
fi

require_absolute_path "state root" "$STATE_ROOT"
require_absolute_path "env file" "$ENV_FILE"
require_absolute_path "backup directory" "$BACKUP_DIR"
STATE_ROOT="$(realpath -m -- "$STATE_ROOT")"
ENV_FILE="$(realpath -m -- "$ENV_FILE")"
BACKUP_DIR="$(realpath -m -- "$BACKUP_DIR")"
require_outside_repo "state root" "$STATE_ROOT"
require_outside_repo "env file" "$ENV_FILE"
require_outside_repo "backup directory" "$BACKUP_DIR"
require_secure_env_file "$ENV_FILE"

POSTGRES_DIR="$STATE_ROOT/postgres"
if [[ ! -d "$POSTGRES_DIR" || -L "$POSTGRES_DIR" ]]; then
  printf 'market Postgres data directory does not exist: %s\n' "$POSTGRES_DIR" >&2
  exit 2
fi
POSTGRES_DIR="$(realpath -m -- "$POSTGRES_DIR")"
if paths_overlap "$BACKUP_DIR" "$POSTGRES_DIR"; then
  echo "backup directory must not overlap the Postgres data directory" >&2
  exit 2
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
  printf 'missing dedicated Compose file: %s\n' "$COMPOSE_FILE" >&2
  exit 2
fi
for command_name in awk date docker realpath sha256sum stat; do
  command -v "$command_name" >/dev/null || {
    printf '%s is required\n' "$command_name" >&2
    exit 2
  }
done

install -d -m 0700 "$BACKUP_DIR"
export PREP_WATCHDECK_MARKET_STATE_DIR="$STATE_ROOT"
export PREP_WATCHDECK_MARKET_ENV_FILE="$ENV_FILE"
compose=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$ENV_FILE"
  --file "$COMPOSE_FILE"
)

CONTAINER_ID="$("${compose[@]}" ps --status running --quiet postgres)"
if [[ -z "$CONTAINER_ID" || "$CONTAINER_ID" == *$'\n'* ]]; then
  echo "exactly one running dedicated market Postgres container is required" >&2
  exit 2
fi
if [[ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' \
  "$CONTAINER_ID")" != "$PROJECT_NAME" ]] || \
  [[ "$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' \
    "$CONTAINER_ID")" != "postgres" ]]; then
  echo "refusing a container outside the dedicated market Compose project" >&2
  exit 2
fi
MOUNT_SOURCE="$(
  docker inspect --format \
    '{{ range .Mounts }}{{ if eq .Destination "/var/lib/postgresql/data" }}{{ .Source }}{{ end }}{{ end }}' \
    "$CONTAINER_ID"
)"
if [[ -z "$MOUNT_SOURCE" ]] || \
  [[ "$(realpath -m -- "$MOUNT_SOURCE")" != "$POSTGRES_DIR" ]]; then
  echo "refusing a container whose Postgres mount does not match the requested state root" >&2
  exit 2
fi
ACTUAL_DATABASE="$(
  "${compose[@]}" exec -T postgres sh -ceu 'printf "%s\n" "$POSTGRES_DB"'
)"
if [[ "$ACTUAL_DATABASE" != "$EXPECTED_DATABASE" ]]; then
  printf 'unexpected target database: %s\n' "$ACTUAL_DATABASE" >&2
  exit 2
fi

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FINAL_PATH="$BACKUP_DIR/prep-watchdeck-market-$TIMESTAMP.dump"
TMP_PATH="$BACKUP_DIR/.prep-watchdeck-market-$TIMESTAMP.dump.$$.tmp"
if [[ -e "$FINAL_PATH" || -e "$TMP_PATH" ]]; then
  echo "backup target already exists" >&2
  exit 2
fi
cleanup() {
  rm -f -- "$TMP_PATH"
}
trap cleanup EXIT

(umask 077; : >"$TMP_PATH")
"${compose[@]}" exec -T postgres sh -ceu '
  export PGPASSWORD="$POSTGRES_PASSWORD"
  exec pg_dump \
    --host=127.0.0.1 \
    --port=5432 \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --format=custom \
    --no-owner \
    --no-privileges
' >"$TMP_PATH"
if [[ ! -s "$TMP_PATH" ]]; then
  echo "pg_dump produced an empty backup" >&2
  exit 2
fi
ARCHIVE_DATABASE="$(
  "${compose[@]}" exec -T postgres pg_restore --list <"$TMP_PATH" \
    | awk -F ': ' '/^;[[:space:]]+dbname: / { value=$2 } END { if (value == "") exit 1; print value }'
)"
if [[ "$ARCHIVE_DATABASE" != "$EXPECTED_DATABASE" ]]; then
  printf 'backup archive database mismatch: %s\n' "$ARCHIVE_DATABASE" >&2
  exit 2
fi

chmod 0600 "$TMP_PATH"
mv -T -- "$TMP_PATH" "$FINAL_PATH"
trap - EXIT
printf 'backup=%s\n' "$FINAL_PATH"
printf 'sha256=%s\n' "$(sha256sum "$FINAL_PATH" | awk '{print $1}')"
echo "source database remains unchanged"
