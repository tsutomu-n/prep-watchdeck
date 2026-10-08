import { expect, test } from "vitest";
import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import { rankingFixture } from "./ranking-test-fixture";
import { bitgetTurnover, formatBitgetTurnover } from "./bitget-turnover";

const now = Date.parse("2026-10-08T03:00:00Z");
const stamp = new Date(now).toISOString();
const row = rankingFixture(undefined, now).rows.find(row => row.asset === "BTC")!;
const instrument = {
  venue: "bitget", venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1,
  sourceSymbol: "BTCUSDT", active: true, marketType: "linear_perpetual", quoteAsset: "USDT",
  quality: "ready", observedAt: stamp, sourceAt: stamp, cycleAt: stamp,
  volume24hRaw: 850_000, volume24hUnit: "quote"
} as UniverseInstrumentArtifact;
const snapshot = { generatedAt: stamp, items: [instrument] };

test("exact Bitget contract supplies its own 24h USDT turnover, including real zero", () => {
  expect(bitgetTurnover(row, snapshot, now).value).toBe(850_000);
  expect(bitgetTurnover(row, { ...snapshot, items: [{ ...instrument, volume24hRaw: 0 }] }, now).value).toBe(0);
  expect(row.quoteTurnover).not.toBe(850_000);
});

test("unknown, stale, partial, wrong-version and ambiguous observations never substitute a value", () => {
  for (const change of [
    { venueInstrumentVersionId: 2 }, { active: false }, { quality: "partial" as const },
    { quoteAsset: "USDC" }, { volume24hUnit: "base" }, { volume24hRaw: null },
    { volume24hRaw: -1 }, { sourceAt: null }, { observedAt: "invalid" },
    { sourceAt: new Date(now - 120_001).toISOString() },
    { sourceAt: new Date(now + 10_000).toISOString() }
  ]) expect(bitgetTurnover(row, { ...snapshot, items: [{ ...instrument, ...change }] }, now).value).toBeNull();
  expect(bitgetTurnover(row, null, now).value).toBeNull();
  expect(bitgetTurnover(row, snapshot, now + 120_001).value).toBeNull();
  expect(bitgetTurnover(row, { ...snapshot, items: [instrument, instrument] }, now).value).toBeNull();
  expect(bitgetTurnover({ ...row, originals: [...row.originals, row.originals[0]] }, snapshot, now).value).toBeNull();
});

test("Bitget notation uses lowercase k/m, preserves missing and honours display decimals", () => {
  for (const [value, expected] of [[0, "0"], [999, "999"], [1000, "1k"],
    [850_000, "850k"], [1_000_000, "1m"], [12_300_000, "12.3m"], [1_000_000_000, "1,000m"]] as const)
    expect(formatBitgetTurnover(value, 2)).toBe(expected);
  expect(formatBitgetTurnover(1250, 2)).toBe("1.25k");
  expect(formatBitgetTurnover(1250, 0)).toBe("1k");
  expect(formatBitgetTurnover(null, 2)).toBe("—");
  expect(formatBitgetTurnover(0.0001, 2)).toBe("<0.01");
});
