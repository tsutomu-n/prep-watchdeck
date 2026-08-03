import { describe, expect, it } from "vitest";
import { rankingPosition } from "./rankings";

describe("ranking helpers", () => {
  it("returns 1-based ranking position and value", () => {
    const rankings = {
      timeframes: {
        "15m": {
          changeUp: [
            { symbol: "ALTUSDT", value: 2.1 },
            { symbol: "THINUSDT", value: 1.4 }
          ]
        }
      },
      meta: {
        timeframes: {
          "15m": {
            changeUp: { limit: 10, totalEligible: 37, excludedNoTrade: true }
          }
        }
      }
    };

    expect(rankingPosition(rankings, "15m", "changeUp", "THINUSDT")).toEqual({
      rank: 2,
      value: 1.4,
      limit: 10,
      totalEligible: 37
    });
  });

  it("returns denominator context for symbols outside the ranking limit", () => {
    const rankings = {
      timeframes: {
        "15m": {
          changeUp: [{ symbol: "ALTUSDT", value: 2.1 }]
        }
      },
      meta: {
        timeframes: {
          "15m": {
            changeUp: { limit: 1, totalEligible: 2, excludedNoTrade: true }
          }
        }
      }
    };

    expect(rankingPosition(rankings, "15m", "changeUp", "BETUSDT")).toEqual({
      rank: null,
      value: null,
      limit: 1,
      totalEligible: 2
    });
  });

  it("falls back to item length for old snapshots without metadata", () => {
    const rankings = {
      timeframes: {
        "15m": {
          changeUp: [
            { symbol: "ALTUSDT", value: 2.1 },
            { symbol: "THINUSDT", value: 1.4 }
          ]
        }
      }
    };

    expect(rankingPosition(rankings, "15m", "changeUp", "THINUSDT")).toEqual({
      rank: 2,
      value: 1.4,
      limit: 2,
      totalEligible: 2
    });
  });

  it("returns null for missing ranking data", () => {
    expect(rankingPosition({}, "15m", "changeUp", "ALTUSDT")).toBeNull();
  });
});
