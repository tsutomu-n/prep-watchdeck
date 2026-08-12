import { describe, expect, it } from "vitest";
import {
  findPerpVenueComparisonItem,
  parsePerpVenueComparisonSummary
} from "./perp-venue-comparison";

const source = (venue: "bitget" | "hyperliquid", status: "ok" | "unavailable") => ({
  venue,
  status,
  sourceSymbol: venue === "bitget" ? "AAVEUSDT" : "AAVE",
  quote: "USDT",
  collateral: venue === "bitget" ? "USDT" : "USDC",
  markPrice: status === "ok" ? (venue === "bitget" ? 100 : 101) : null,
  fundingRate: status === "ok" ? 0.0001 : null,
  fundingIntervalHours: venue === "bitget" ? 8 : 1,
  fundingRatePerHour: status === "ok" ? (venue === "bitget" ? 0.0000125 : 0.0001) : null,
  openInterestBase: status === "ok" ? 10 : null,
  openInterestNotional: status === "ok" ? 1000 : null,
  volume24hNotional: status === "ok" ? 1_000_000 : null,
  observedAt: status === "ok" ? 1_780_000_000_000 : null,
  sourceAt: status === "ok" && venue === "bitget" ? 1_780_000_000_000 : null,
  error: status === "unavailable" ? "TimeoutError" : null
});

describe("perp venue comparison payload guard", () => {
  it("accepts ready and partial items while dropping contradictory items", () => {
    const summary = parsePerpVenueComparisonSummary({
      schemaVersion: 1,
      mode: "perp_venue_comparison_v1",
      generatedAt: 1_780_000_000_000,
      refreshIntervalSeconds: 300,
      sources: [
        { venue: "bitget", status: "ok", observedAt: 1_780_000_000_000, error: null },
        {
          venue: "hyperliquid",
          status: "unavailable",
          observedAt: null,
          error: "TimeoutError"
        }
      ],
      items: [
        {
          symbol: "AAVEUSDT",
          asset: "AAVE",
          status: "ready",
          markSpreadPct: 1,
          sources: [source("bitget", "ok"), source("hyperliquid", "ok")]
        },
        {
          symbol: "DOGEUSDT",
          asset: "DOGE",
          status: "partial",
          markSpreadPct: null,
          sources: [
            { ...source("bitget", "ok"), sourceSymbol: "DOGEUSDT" },
            { ...source("hyperliquid", "unavailable"), sourceSymbol: "DOGE" }
          ]
        },
        {
          symbol: "BADUSDT",
          asset: "BAD",
          status: "ready",
          markSpreadPct: null,
          sources: [source("bitget", "ok"), source("hyperliquid", "unavailable")]
        }
      ]
    });

    expect(summary?.items.map((item) => item.symbol)).toEqual(["AAVEUSDT", "DOGEUSDT"]);
    expect(summary?.sources?.map((item) => item.status)).toEqual(["ok", "unavailable"]);
    expect(findPerpVenueComparisonItem(summary, "AAVEUSDT")?.markSpreadPct).toBe(1);
    expect(findPerpVenueComparisonItem(summary, "MISSINGUSDT")).toBeNull();
  });

  it("rejects an invalid top-level contract", () => {
    expect(parsePerpVenueComparisonSummary({ schemaVersion: 1, items: [] })).toBeNull();
  });
});
