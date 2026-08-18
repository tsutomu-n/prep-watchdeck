#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
UV_BIN="${PREP_WATCHDECK_MARKET_UV_BIN:-$(command -v uv || true)}"
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  printf 'uv executable not found\n' >&2
  exit 2
fi

cd "$ROOT_DIR/apps/market-core"

funding_status=0
"$UV_BIN" run watchdeck-market funding-sync || funding_status=$?

maintenance_status=0
"$UV_BIN" run watchdeck-market maintenance "$@" || maintenance_status=$?

if (( maintenance_status != 0 )); then
  exit "$maintenance_status"
fi
if (( funding_status != 0 )); then
  printf 'maintenance completed, but funding sync requires attention\n' >&2
  exit "$funding_status"
fi
