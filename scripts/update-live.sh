#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib/resolve-state-paths.sh"
resolve_watchdeck_state_paths "$ROOT_DIR"

LIVE_MAX_SYMBOLS="${LIVE_MAX_SYMBOLS:-30}"
TEMPLATE="${TEMPLATE:-balanced}"

echo "== update live snapshot =="
echo "template=${TEMPLATE} live_max_symbols=${LIVE_MAX_SYMBOLS}"
print_watchdeck_state_paths

cd "$ROOT_DIR/apps/scanner-core"
PREP_WATCHDECK_LIVE_MAX_SYMBOLS="$LIVE_MAX_SYMBOLS" \
  uv run watchdeck scan --source live --template "$TEMPLATE"

echo "== latest snapshot =="
cd "$ROOT_DIR"
bun --eval 'const f = Bun.file(process.env.SCANNER_SNAPSHOT_PATH); const j = await f.json(); console.log(`${j.source.dataSource} ${j.snapshotStatus} rows=${j.rows.length} dataAsOf=${new Date(j.dataAsOf).toISOString()}`);'
