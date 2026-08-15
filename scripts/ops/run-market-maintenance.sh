#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MARKET_STATE_ROOT="${PREP_WATCHDECK_MARKET_STATE_DIR:-$HOME/.local/share/prep-watchdeck-market}"
UV_BIN="${PREP_WATCHDECK_MARKET_UV_BIN:-uv}"

if [[ "$MARKET_STATE_ROOT" != /* || "$MARKET_STATE_ROOT" == *$'\n'* ]]; then
  printf 'PREP_WATCHDECK_MARKET_STATE_DIR must be an absolute single-line path\n' >&2
  exit 2
fi

export PREP_WATCHDECK_MARKET_STATE_DIR="$MARKET_STATE_ROOT"
install -d -m 0700 "$MARKET_STATE_ROOT" "$MARKET_STATE_ROOT/archive"

cd "$ROOT_DIR/apps/market-core"
exec "$UV_BIN" run watchdeck-market maintenance "$@"
