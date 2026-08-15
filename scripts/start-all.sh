#!/usr/bin/env bash
set -euo pipefail

SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-/usr/bin/systemctl}"

if [[ ! -x "$SYSTEMCTL_BIN" ]]; then
  printf 'systemctl is not executable: %s\n' "$SYSTEMCTL_BIN" >&2
  exit 2
fi

units=(
  prep-watchdeck-market-db.service
  prep-watchdeck-market.service
  prep-watchdeck-web.service
  prep-watchdeck-market-maintenance.timer
)

for unit in "${units[@]}"; do
  if ! "$SYSTEMCTL_BIN" --user cat "$unit" >/dev/null 2>&1; then
    printf 'unit is not installed: %s\n' "$unit" >&2
    printf 'run scripts/ops/install-user-services.sh --apply first\n' >&2
    exit 2
  fi
done

"$SYSTEMCTL_BIN" --user start prep-watchdeck-market-db.service
"$SYSTEMCTL_BIN" --user start prep-watchdeck-market.service
"$SYSTEMCTL_BIN" --user start prep-watchdeck-web.service
"$SYSTEMCTL_BIN" --user start prep-watchdeck-market-maintenance.timer

printf 'url=http://127.0.0.1:5173/\n'
"$SYSTEMCTL_BIN" --user show "${units[@]}" \
  -p Id -p ActiveState -p SubState -p MainPID -p NRestarts --no-pager
