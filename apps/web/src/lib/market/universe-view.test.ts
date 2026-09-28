import { describe, expect, test } from "vitest";
import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import { coverageLabel, filterAndSortUniverse, formatBidAsk, formatPrice, formatTimestamp, groupVenueCounts, sortNativeRows, spreadBps } from "./universe-view";

test("native raw sort includes every row and puts missing values last", () => {
  const a = instrument("bitget:AAAUSDT", "AAA", "bitget", null, "ready");
  const b = instrument("bitget:BBBUSDT", "BBB", "bitget", null, "ready");
  const c = instrument("bitget:CCCUSDT", "CCC", "bitget", null, "ready");
  const now = Date.now();
  for (const item of [a, b, c]) {
    item.observedAt = new Date(now - 1_000).toISOString();
    item.sourceAt = new Date(now - 1_000).toISOString();
  }
  a.fundingRatePerHour = null;
  b.fundingRatePerHour = 0.01;
  c.fundingRatePerHour = 0.02;
  expect(sortNativeRows([a, b, c], "funding", "desc", () => null, now)
    .map((item) => item.venueInstrumentId)).toEqual([c.venueInstrumentId, b.venueInstrumentId, a.venueInstrumentId]);
  c.sourceAt = new Date(now - 121_000).toISOString();
  expect(sortNativeRows([a, b, c], "funding", "desc", () => null, now)
    .map((item) => item.venueInstrumentId)).toEqual([b.venueInstrumentId, a.venueInstrumentId, c.venueInstrumentId]);
});

test("spread uses one valid bid/ask snapshot", () => {
  expect(spreadBps(100, 100)).toBe(0);
  expect(spreadBps(99, 101)).toBe(200);
  expect(spreadBps(101, 100)).toBeNull();
  expect(spreadBps(null, 100)).toBeNull();
});

test("small prices remain nonzero and bid/ask do not collapse to the same text", () => {
  expect(formatPrice(0.00000012)).not.toBe("0");
  const [bid, ask] = formatBidAsk(0.00000121, 0.00000126);
  expect(bid).not.toBe(ask);
  expect(formatPrice(1e-18)).not.toBe("0");
  expect(formatPrice(null)).toBe("—");
  expect(formatPrice(Infinity)).toBe("—");
  expect(formatPrice(0.25)).toBe("0.25");
  expect(formatPrice(100.25)).toContain("100");
});

test("market timestamps use JST rather than the browser time zone", () => {
  expect(formatTimestamp("2026-09-09T23:00:00Z")).toBe("09/10 08:00:00");
});

describe("Universe Explorer filtering", () => {
  test("sorts base then venue and keeps coverage, venue, search and quality explicit", () => {
    const items = [
      instrument("hyperliquid:BTC", "BTC", "hyperliquid", "crypto:BTC:linear-perp", "ready"),
      instrument("aster:ETHUSDT", "ETH", "aster", null, "partial"),
      instrument("bitget:BTCUSDT", "BTC", "bitget", "crypto:BTC:linear-perp", "ready")
    ];

    expect(
      filterAndSortUniverse(items, {
        search: "",
        venue: "all",
        coverage: "all",
        quality: "all"
      }).map((item) => item.venueInstrumentId)
    ).toEqual(["bitget:BTCUSDT", "hyperliquid:BTC", "aster:ETHUSDT"]);
    expect(
      filterAndSortUniverse(items, {
        search: "btc",
        venue: "hyperliquid",
        coverage: "multi",
        quality: "ready"
      }).map((item) => item.venueInstrumentId)
    ).toEqual(["hyperliquid:BTC"]);
    expect(
      filterAndSortUniverse(items, {
        search: "",
        venue: "all",
        coverage: "single",
        quality: "partial"
      }).map((item) => item.venueInstrumentId)
    ).toEqual(["aster:ETHUSDT"]);
  });

  test("counts distinct venues and presents coverage as a neutral axis", () => {
    const items = [
      instrument("bitget:BTCUSDT", "BTC", "bitget", "crypto:BTC:linear-perp", "ready"),
      instrument("hyperliquid:BTC", "BTC", "hyperliquid", "crypto:BTC:linear-perp", "ready"),
      instrument("aster:ETHUSDT", "ETH", "aster", null, "ready")
    ];
    const counts = groupVenueCounts(items);
    expect(counts.get("crypto:BTC:linear-perp")).toBe(2);
    expect(coverageLabel(items[0], counts)).toBe("2 Venue");
    expect(coverageLabel(items[2], counts)).toBe("未group");
  });
});

function instrument(
  venueInstrumentId: string,
  baseAsset: string,
  venue: UniverseInstrumentArtifact["venue"],
  groupId: string | null,
  quality: UniverseInstrumentArtifact["quality"]
) {
  return {
    venueInstrumentId,
    baseAsset,
    venue,
    groupId,
    sourceSymbol: venueInstrumentId.split(":")[1],
    quoteAsset: "USDT",
    settleAsset: "USDT",
    active: true,
    quality
  } as UniverseInstrumentArtifact;
}
