#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DATABASE_CONTAINER=""

cleanup() {
  if [[ -n "$TEST_DATABASE_CONTAINER" ]]; then
    docker rm --force "$TEST_DATABASE_CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  if [[ ! -S /var/run/docker.sock ]]; then
    printf '%s\n' 'local Docker socket is unavailable at /var/run/docker.sock' >&2
    exit 2
  fi
  export DOCKER_HOST=unix:///var/run/docker.sock
  unset DOCKER_CONTEXT
  TEST_DATABASE_CONTAINER="prep-watchdeck-verify-${UID:-0}-$$"
  docker run --detach --rm \
    --name "$TEST_DATABASE_CONTAINER" \
    --env POSTGRES_DB=prep_watchdeck_test \
    --env POSTGRES_USER=prep_watchdeck_test \
    --env POSTGRES_PASSWORD=watchdeck_test_only \
    --publish 127.0.0.1::5432 \
    postgres:17@sha256:e42539a54ee3e82e21f19d7eded61b579869585f86b90b5e851ff0d3dd8b4001 \
    >/dev/null
  for _attempt in $(seq 1 30); do
    if docker exec "$TEST_DATABASE_CONTAINER" \
      pg_isready -U prep_watchdeck_test -d prep_watchdeck_test >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  if ! docker exec "$TEST_DATABASE_CONTAINER" \
    pg_isready -U prep_watchdeck_test -d prep_watchdeck_test >/dev/null 2>&1; then
    printf 'isolated verification Postgres did not become ready\n' >&2
    exit 1
  fi
  test_database_port="$(docker port "$TEST_DATABASE_CONTAINER" 5432/tcp | sed -n '1s/.*://p')"
  if [[ ! "$test_database_port" =~ ^[0-9]+$ ]]; then
    printf 'isolated verification Postgres port could not be resolved\n' >&2
    exit 1
  fi
  export TEST_DATABASE_URL="postgresql://prep_watchdeck_test:watchdeck_test_only@127.0.0.1:${test_database_port}/prep_watchdeck_test"
  printf 'isolatedPostgres=started port=%s\n' "$test_database_port"
else
  if ! TEST_DATABASE_URL="$TEST_DATABASE_URL" \
    bun "$ROOT_DIR/scripts/lib/validate-test-database-url.mjs"; then
    printf '%s\n' 'external TEST_DATABASE_URL is not an isolated prep-watchdeck test database' >&2
    exit 2
  fi
  printf '%s\n' 'isolatedPostgres=external TEST_DATABASE_URL supplied'
fi

echo "== repository maintenance tests =="
cd "$ROOT_DIR"
bun test \
  scripts/maintenance/document-metadata.test.mjs \
  scripts/maintenance/document-links.test.mjs \
  scripts/maintenance/monitoring-only-boundary.test.mjs \
  scripts/maintenance/test-database-url.test.mjs \
  scripts/maintenance/web-port.test.mjs \
  scripts/ops/install-user-services.test.mjs \
  scripts/ops/run-isolated-shadow.test.mjs

echo "== document metadata =="
bun scripts/maintenance/check-document-metadata.mjs

echo "== document links =="
bun scripts/maintenance/check-document-links.mjs

echo "== workspace lock =="
uv lock --check

echo "== market-core: pytest =="
cd "$ROOT_DIR/apps/market-core"
uv run python -m pytest -q

echo "== market-core: ruff check =="
uv run ruff check src tests

echo "== market-core: ruff format --check =="
uv run ruff format --check src tests

echo "== market-core: pyrefly check =="
uv run pyrefly check

echo "== web: generated types =="
cd "$ROOT_DIR/apps/web"
bun run generate:types

echo "== web: bun test =="
bun test

echo "== web: svelte-check =="
bun run check

echo "== web: build =="
bun run build

echo "== web: Playwright E2E =="
bun run test:e2e
