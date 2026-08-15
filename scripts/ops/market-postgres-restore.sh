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
  bash scripts/ops/market-postgres-restore.sh \
    --state-root /absolute/repo-external/state \
    --env-file /absolute/repo-external/postgres.env \
    --backup /absolute/repo-external/prep-watchdeck-market-TIMESTAMP.dump \
    --confirm-target prep_watchdeck_market \
    --apply

Inspects the archive, rejects active target connections, then restores only the dedicated
market database in one transaction. Stop watchdeck-market before running it.
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

require_secure_file() {
  local label="$1"
  local path="$2"
  if [[ ! -f "$path" || -L "$path" || ! -O "$path" ]]; then
    printf '%s must be a regular, non-symlink file owned by the current user: %s\n' \
      "$label" "$path" >&2
    exit 2
  fi
  if [[ "$(stat -c '%a' "$path")" != "600" ]]; then
    printf '%s mode must be 0600: %s\n' "$label" "$path" >&2
    exit 2
  fi
}

STATE_ROOT=""
ENV_FILE=""
BACKUP_PATH=""
CONFIRM_TARGET=""
APPLY=false

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
    --backup)
      require_value "$@"
      BACKUP_PATH="$2"
      shift 2
      ;;
    --confirm-target)
      require_value "$@"
      CONFIRM_TARGET="$2"
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
      printf 'unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$STATE_ROOT" || -z "$ENV_FILE" || -z "$BACKUP_PATH" ]]; then
  usage >&2
  exit 2
fi
if [[ "$CONFIRM_TARGET" != "$EXPECTED_DATABASE" || "$APPLY" != true ]]; then
  echo "restore requires --confirm-target prep_watchdeck_market and --apply" >&2
  exit 2
fi

require_absolute_path "state root" "$STATE_ROOT"
require_absolute_path "env file" "$ENV_FILE"
require_absolute_path "backup" "$BACKUP_PATH"
STATE_ROOT="$(realpath -m -- "$STATE_ROOT")"
ENV_FILE="$(realpath -m -- "$ENV_FILE")"
BACKUP_PATH="$(realpath -m -- "$BACKUP_PATH")"
require_outside_repo "state root" "$STATE_ROOT"
require_outside_repo "env file" "$ENV_FILE"
require_outside_repo "backup" "$BACKUP_PATH"
require_secure_file "env file" "$ENV_FILE"
require_secure_file "backup" "$BACKUP_PATH"

POSTGRES_DIR="$STATE_ROOT/postgres"
if [[ ! -d "$POSTGRES_DIR" || -L "$POSTGRES_DIR" ]]; then
  printf 'market Postgres data directory does not exist: %s\n' "$POSTGRES_DIR" >&2
  exit 2
fi
POSTGRES_DIR="$(realpath -m -- "$POSTGRES_DIR")"
case "$BACKUP_PATH/" in
  "$POSTGRES_DIR/"*)
    echo "backup must not be stored inside the Postgres data directory" >&2
    exit 2
    ;;
esac
if [[ ! -f "$COMPOSE_FILE" ]]; then
  printf 'missing dedicated Compose file: %s\n' "$COMPOSE_FILE" >&2
  exit 2
fi
for command_name in awk docker realpath stat; do
  command -v "$command_name" >/dev/null || {
    printf '%s is required\n' "$command_name" >&2
    exit 2
  }
done

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

ARCHIVE_DATABASE="$(
  "${compose[@]}" exec -T postgres pg_restore --list <"$BACKUP_PATH" \
    | awk -F ': ' '/^;[[:space:]]+dbname: / { value=$2 } END { if (value == "") exit 1; print value }'
)"
if [[ "$ARCHIVE_DATABASE" != "$EXPECTED_DATABASE" ]]; then
  printf 'backup archive database mismatch: %s\n' "$ARCHIVE_DATABASE" >&2
  exit 2
fi

ACTIVE_CONNECTIONS="$(
  "${compose[@]}" exec -T postgres sh -ceu '
    export PGPASSWORD="$POSTGRES_PASSWORD"
    exec psql \
      --host=127.0.0.1 \
      --port=5432 \
      --username="$POSTGRES_USER" \
      --dbname=postgres \
      --no-align \
      --tuples-only \
      --command="SELECT count(*) FROM pg_stat_activity WHERE datname = '\''prep_watchdeck_market'\'' AND pid <> pg_backend_pid();"
  '
)"
if [[ "$ACTIVE_CONNECTIONS" != "0" ]]; then
  printf 'target database has active connections; stop watchdeck-market first: %s\n' \
    "$ACTIVE_CONNECTIONS" >&2
  exit 2
fi

"${compose[@]}" exec -T postgres sh -ceu '
  export PGPASSWORD="$POSTGRES_PASSWORD"
  exec pg_restore \
    --host=127.0.0.1 \
    --port=5432 \
    --username="$POSTGRES_USER" \
    --dbname="$POSTGRES_DB" \
    --clean \
    --if-exists \
    --single-transaction \
    --exit-on-error \
    --no-owner \
    --no-privileges
' <"$BACKUP_PATH"

printf 'restored=%s\n' "$BACKUP_PATH"
printf 'target=%s\n' "$EXPECTED_DATABASE"
