#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/resolve-state-paths.sh"
source "$ROOT_DIR/scripts/lib/select-web-port.sh"
resolve_watchdeck_state_paths "$ROOT_DIR"

REQUESTED_PORT="${PORT:-5173}"
PORT="$(select_watchdeck_web_port "$REQUESTED_PORT")"
LIVE_MAX_SYMBOLS="${LIVE_MAX_SYMBOLS:-30}"
TEMPLATE="${TEMPLATE:-balanced}"

LIVE_MAX_SYMBOLS="$LIVE_MAX_SYMBOLS" TEMPLATE="$TEMPLATE" "$ROOT_DIR/scripts/update-live.sh"

echo "== start web =="
echo "url=http://127.0.0.1:${PORT}/"
echo "template=${TEMPLATE} live_max_symbols=${LIVE_MAX_SYMBOLS}"
print_watchdeck_state_paths

cd "$ROOT_DIR/apps/web"
PREP_WATCHDECK_LIVE_TEMPLATE="$TEMPLATE" \
  PREP_WATCHDECK_LIVE_MAX_SYMBOLS="$LIVE_MAX_SYMBOLS" \
  bun run dev -- --port "$PORT" --strictPort
