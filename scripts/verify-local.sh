#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== repository maintenance tests =="
cd "$ROOT_DIR"
bun test \
  scripts/maintenance/document-metadata.test.mjs \
  scripts/maintenance/document-links.test.mjs \
  scripts/maintenance/monitoring-only-boundary.test.mjs \
  scripts/maintenance/retired-records-archive.test.mjs \
  scripts/maintenance/state-dir.test.mjs \
  scripts/maintenance/web-port.test.mjs \
  scripts/ops/watchdeck-daily-summary.test.mjs

echo "== document metadata =="
bun scripts/maintenance/check-document-metadata.mjs

echo "== document links =="
bun scripts/maintenance/check-document-links.mjs

echo "== scanner-core: pytest =="
cd "$ROOT_DIR/apps/scanner-core"
uv run python -m pytest -q

echo "== scanner-core: ruff check =="
uv run ruff check .

echo "== scanner-core: ruff format --check =="
uv run ruff format --check .

echo "== scanner-core: pyrefly check =="
uv run pyrefly check

echo "== web: bun test =="
cd "$ROOT_DIR/apps/web"
bun test

echo "== web: svelte-check =="
bun run check

echo "== web: build =="
bun run build

echo "== web: Playwright E2E =="
bun run test:e2e
