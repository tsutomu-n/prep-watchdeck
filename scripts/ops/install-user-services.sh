#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

mode="dry-run"
repo_root="$DEFAULT_REPO_ROOT"
state_root="${PREP_WATCHDECK_STATE_DIR:-$HOME/.local/share/prep-watchdeck}"
unit_dir="$HOME/.config/systemd/user"
systemctl_bin="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

usage() {
  printf '%s\n' \
    "Usage: $0 [--dry-run|--check|--apply] [--repo-root PATH] [--state-root PATH]" \
    "          [--unit-dir PATH] [--systemctl-bin PATH]"
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
    --dry-run)
      mode="dry-run"
      shift
      ;;
    --check)
      mode="check"
      shift
      ;;
    --apply)
      mode="apply"
      shift
      ;;
    --repo-root)
      require_value "$@"
      repo_root="$2"
      shift 2
      ;;
    --state-root)
      require_value "$@"
      state_root="$2"
      shift 2
      ;;
    --unit-dir)
      require_value "$@"
      unit_dir="$2"
      shift 2
      ;;
    --systemctl-bin)
      require_value "$@"
      systemctl_bin="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
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
require_absolute_path "state root" "$state_root"
require_absolute_path "unit directory" "$unit_dir"
require_absolute_path "systemctl binary" "$systemctl_bin"

if [[ ! -d "$repo_root" ]]; then
  printf 'repo root does not exist: %s\n' "$repo_root" >&2
  exit 2
fi
repo_root="$(cd "$repo_root" && pwd)"

home_dir="${HOME:?HOME is required}"
uv_bin="$home_dir/.local/bin/uv"
template_dir="$repo_root/config/systemd"
unit_names=("prep-watchdeck-service.service" "prep-watchdeck-web.service")

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
state_replacement="$(escape_sed_replacement "$state_root")"
home_replacement="$(escape_sed_replacement "$home_dir")"
uv_replacement="$(escape_sed_replacement "$uv_bin")"

for name in "${unit_names[@]}"; do
  sed \
    -e "s|@REPO_ROOT@|$repo_replacement|g" \
    -e "s|@STATE_ROOT@|$state_replacement|g" \
    -e "s|@HOME_DIR@|$home_replacement|g" \
    -e "s|@UV_BIN@|$uv_replacement|g" \
    "$template_dir/$name.in" >"$render_dir/$name"
done

printf 'mode=%s repoRoot=%s stateRoot=%s unitDir=%s\n' \
  "$mode" "$repo_root" "$state_root" "$unit_dir"

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

if [[ ! -x "$systemctl_bin" ]]; then
  printf 'systemctl binary is not executable: %s\n' "$systemctl_bin" >&2
  exit 2
fi

mkdir -p "$unit_dir"
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
"$systemctl_bin" --user enable "${unit_names[@]}"
printf 'installed units; services were not started or restarted\n'
