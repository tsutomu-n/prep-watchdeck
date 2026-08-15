#!/usr/bin/env bash
set -euo pipefail

MARKET_STATE_ROOT="${PREP_WATCHDECK_MARKET_STATE_DIR:-$HOME/.local/share/prep-watchdeck-market}"
if [[ "$MARKET_STATE_ROOT" != /* || "$MARKET_STATE_ROOT" == *$'\n'* ]]; then
  printf 'PREP_WATCHDECK_MARKET_STATE_DIR must be an absolute single-line path\n' >&2
  exit 2
fi

printf '%s\n' 'manual one-shot collection was removed; the market service updates continuously.'
printf 'stateDir=%s\n' "$MARKET_STATE_ROOT"

MARKET_WEB_ORIGIN="${PREP_WATCHDECK_MARKET_WEB_ORIGIN:-http://127.0.0.1:5173}"
if ! MARKET_WEB_ORIGIN="$MARKET_WEB_ORIGIN" bun --eval '
let valid = false;
try {
  const value = new URL(process.env.MARKET_WEB_ORIGIN);
  const port = Number(value.port);
  valid =
    value.protocol === "http:" &&
    ["127.0.0.1", "localhost", "[::1]"].includes(value.hostname) &&
    value.username === "" &&
    value.password === "" &&
    value.pathname === "/" &&
    value.search === "" &&
    value.hash === "" &&
    Number.isInteger(port) &&
    port >= 1 &&
    port <= 65535;
} catch {}
if (!valid) process.exit(2);
'; then
  printf 'PREP_WATCHDECK_MARKET_WEB_ORIGIN must be a loopback HTTP origin with an explicit port\n' >&2
  exit 2
fi

curl --fail-with-body --silent --show-error "$MARKET_WEB_ORIGIN/api/market-data" |
  bun --eval '
const bundle = JSON.parse(await Bun.stdin.text());
for (const [name, value] of Object.entries(bundle)) {
  console.log(`${name} status=${value.status} generatedAt=${value.generatedAt}`);
}
'
