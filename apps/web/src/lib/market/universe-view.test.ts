import { describe, expect, test } from "vitest";
import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import { coverageLabel, filterAndSortUniverse, groupVenueCounts } from "./universe-view";

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
