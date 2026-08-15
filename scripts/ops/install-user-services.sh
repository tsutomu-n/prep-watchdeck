#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

mode="dry-run"
repo_root="$DEFAULT_REPO_ROOT"
market_state_root="${PREP_WATCHDECK_MARKET_STATE_DIR:-$HOME/.local/share/prep-watchdeck-market}"
market_env_file="${PREP_WATCHDECK_MARKET_ENV_FILE:-$HOME/.config/prep-watchdeck-market/postgres.env}"
unit_dir="$HOME/.config/systemd/user"
systemctl_bin="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"
uv_bin="${UV_BIN:-$HOME/.local/bin/uv}"
bun_bin="${BUN_BIN:-$HOME/.local/share/bun/bin/bun}"
docker_bin="${DOCKER_BIN:-/usr/bin/docker}"

usage() {
  printf '%s\n' \
    "Usage: $0 [--dry-run|--check|--apply] [--repo-root PATH]" \
    "          [--state-root PATH] [--market-env-file PATH] [--unit-dir PATH]" \
    "          [--systemctl-bin PATH] [--uv-bin PATH] [--bun-bin PATH] [--docker-bin PATH]"
}

require_value() {
  if [[ $# -lt 2 || -z "$2" ]]; then
    printf 'missing value for %s\n' "$1" >&2
    usage >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) mode="dry-run"; shift ;;
    --check) mode="check"; shift ;;
    --apply) mode="apply"; shift ;;
    --repo-root) require_value "$@"; repo_root="$2"; shift 2 ;;
    --state-root) require_value "$@"; market_state_root="$2"; shift 2 ;;
    --market-env-file) require_value "$@"; market_env_file="$2"; shift 2 ;;
    --unit-dir) require_value "$@"; unit_dir="$2"; shift 2 ;;
    --systemctl-bin) require_value "$@"; systemctl_bin="$2"; shift 2 ;;
    --uv-bin) require_value "$@"; uv_bin="$2"; shift 2 ;;
    --bun-bin) require_value "$@"; bun_bin="$2"; shift 2 ;;
    --docker-bin) require_value "$@"; docker_bin="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

require_absolute_path() {
  local label="$1"
  local value="$2"
  if [[ "$value" != /* || "$value" == *$'\n'* ]]; then
    printf '%s must be an absolute single-line path: %s\n' "$label" "$value" >&2
    exit 2
  fi
}

require_absolute_path "repo root" "$repo_root"
require_absolute_path "market state root" "$market_state_root"
require_absolute_path "market env file" "$market_env_file"
require_absolute_path "unit directory" "$unit_dir"
require_absolute_path "systemctl binary" "$systemctl_bin"
require_absolute_path "uv binary" "$uv_bin"
require_absolute_path "bun binary" "$bun_bin"
require_absolute_path "docker binary" "$docker_bin"

if [[ ! -d "$repo_root" ]]; then
  printf 'repo root does not exist: %s\n' "$repo_root" >&2
  exit 2
fi
repo_root="$(cd "$repo_root" && pwd)"

home_dir="${HOME:?HOME is required}"
template_dir="$repo_root/config/systemd"
unit_names=(
  "prep-watchdeck-market-db.service"
  "prep-watchdeck-market.service"
  "prep-watchdeck-market-maintenance.service"
  "prep-watchdeck-market-maintenance.timer"
  "prep-watchdeck-web.service"
)
enabled_units=(
  "prep-watchdeck-market-db.service"
  "prep-watchdeck-market.service"
  "prep-watchdeck-web.service"
  "prep-watchdeck-market-maintenance.timer"
)

for name in "${unit_names[@]}"; do
  if [[ ! -f "$template_dir/$name.in" ]]; then
    printf 'missing unit template: %s\n' "$template_dir/$name.in" >&2
    exit 2
  fi
done

escape_sed_replacement() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//&/\\&}"
  value="${value//|/\\|}"
  printf '%s' "$value"
}

render_dir="$(mktemp -d)"
trap 'rm -r -- "$render_dir"' EXIT

repo_replacement="$(escape_sed_replacement "$repo_root")"
state_replacement="$(escape_sed_replacement "$market_state_root")"
env_replacement="$(escape_sed_replacement "$market_env_file")"
home_replacement="$(escape_sed_replacement "$home_dir")"
uv_replacement="$(escape_sed_replacement "$uv_bin")"
bun_replacement="$(escape_sed_replacement "$bun_bin")"
docker_replacement="$(escape_sed_replacement "$docker_bin")"

for name in "${unit_names[@]}"; do
  sed \
    -e "s|@REPO_ROOT@|$repo_replacement|g" \
    -e "s|@MARKET_STATE_ROOT@|$state_replacement|g" \
    -e "s|@MARKET_ENV_FILE@|$env_replacement|g" \
    -e "s|@HOME_DIR@|$home_replacement|g" \
    -e "s|@UV_BIN@|$uv_replacement|g" \
    -e "s|@BUN_BIN@|$bun_replacement|g" \
    -e "s|@DOCKER_BIN@|$docker_replacement|g" \
    "$template_dir/$name.in" >"$render_dir/$name"
  if grep -Eq '@[A-Z_]+@' "$render_dir/$name"; then
    printf 'unresolved unit placeholder: %s\n' "$name" >&2
    exit 2
  fi
done

printf 'mode=%s repoRoot=%s stateRoot=%s envFile=%s unitDir=%s\n' \
  "$mode" "$repo_root" "$market_state_root" "$market_env_file" "$unit_dir"

if [[ "$mode" == "dry-run" ]]; then
  for name in "${unit_names[@]}"; do
    target="$unit_dir/$name"
    if [[ -f "$target" ]]; then
      diff -u "$target" "$render_dir/$name" || true
    else
      diff -u /dev/null "$render_dir/$name" || true
    fi
  done
  exit 0
fi

if [[ ! -f "$market_env_file" || ! -O "$market_env_file" ]]; then
  printf 'market env file must exist and be owned by the current user: %s\n' "$market_env_file" >&2
  exit 2
fi
if [[ "$(stat -c %a "$market_env_file")" != "600" ]]; then
  printf 'market env file mode must be 600: %s\n' "$market_env_file" >&2
  exit 2
fi
market_database_url=""
while IFS= read -r line || [[ -n "$line" ]]; do
  case "$line" in
    PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=* | \
    PREP_WATCHDECK_MARKET_DB_PORT=*)
      printf 'production env file must not override the database target boundary\n' >&2
      exit 2
      ;;
    PREP_WATCHDECK_MARKET_DATABASE_URL=*)
      if [[ -n "$market_database_url" ]]; then
        printf 'market env file contains duplicate database URL entries\n' >&2
        exit 2
      fi
      market_database_url="${line#*=}"
      ;;
  esac
done <"$market_env_file"
case "$market_database_url" in
  postgresql://prep_watchdeck_market:?*@127.0.0.1:55432/prep_watchdeck_market | \
  postgres://prep_watchdeck_market:?*@127.0.0.1:55432/prep_watchdeck_market) ;;
  *)
    printf 'market env file database URL must target the dedicated local database\n' >&2
    exit 2
    ;;
esac

if [[ "$mode" == "check" ]]; then
  drift=0
  for name in "${unit_names[@]}"; do
    target="$unit_dir/$name"
    if [[ ! -f "$target" ]] || ! cmp -s "$target" "$render_dir/$name"; then
      printf 'unit drift detected: %s\n' "$target" >&2
      drift=1
    fi
  done
  if [[ "$drift" -ne 0 ]]; then
    exit 1
  fi
  printf 'units match rendered configuration\n'
  exit 0
fi

for executable in "$systemctl_bin" "$uv_bin" "$bun_bin" "$docker_bin"; do
  if [[ ! -x "$executable" ]]; then
    printf 'required binary is not executable: %s\n' "$executable" >&2
    exit 2
  fi
done
install -d -m 0700 "$market_state_root" "$market_state_root/postgres" "$unit_dir"
backup_suffix="$(date +%Y%m%d-%H%M%S).$$"
for name in "${unit_names[@]}"; do
  target="$unit_dir/$name"
  if [[ -f "$target" ]]; then
    cp -p "$target" "$target.bak.$backup_suffix"
    printf 'backup=%s\n' "$target.bak.$backup_suffix"
  fi
  install -m 0644 "$render_dir/$name" "$target.tmp.$$"
  mv "$target.tmp.$$" "$target"
done

"$systemctl_bin" --user daemon-reload
"$systemctl_bin" --user enable "${enabled_units[@]}"
printf 'installed units; services and timer were not started or restarted\n'
