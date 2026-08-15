#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/select-web-port.sh"

MARKET_STATE_ROOT="${PREP_WATCHDECK_MARKET_STATE_DIR:-$HOME/.local/share/prep-watchdeck-market}"
if [[ "$MARKET_STATE_ROOT" != /* || "$MARKET_STATE_ROOT" == *$'\n'* ]]; then
  printf 'PREP_WATCHDECK_MARKET_STATE_DIR must be an absolute single-line path\n' >&2
  exit 2
fi

REQUESTED_PORT="${PORT:-5173}"
PORT="$(select_watchdeck_web_port "$REQUESTED_PORT")"
export PREP_WATCHDECK_MARKET_STATE_DIR="$MARKET_STATE_ROOT"

printf 'url=http://127.0.0.1:%s/\n' "$PORT"
printf 'stateDir=%s\n' "$MARKET_STATE_ROOT"
printf 'artifactDir=%s\n' "$MARKET_STATE_ROOT/artifacts"
printf 'controlPath=%s\n' "$MARKET_STATE_ROOT/control/selection.json"
printf 'pastNotesDir=%s\n' "$MARKET_STATE_ROOT/past-notes"

cd "$ROOT_DIR/apps/web"
bun run generate:types
exec bun run dev -- --port "$PORT" --strictPort
