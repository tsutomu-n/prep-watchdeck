import { describe, expect, it } from "vitest";
import { findMarketComparisonItem, parseMarketComparisonSummary } from "./market-comparison";

const source = (name: "bitget" | "hyperliquid" | "bybit", price: number) => ({
  source: name,
  status: "ok",
  sourceSymbol: name === "hyperliquid" ? "BTC" : "BTCUSDT",
  quote: "USDT",
  markPrice: price,
  observedAt: 1_780_000_000_000,
  sourceAt: name === "hyperliquid" ? null : 1_780_000_000_000,
  error: null
});

describe("market comparison payload guard", () => {
  it("accepts a complete three-source comparison", () => {
    const summary = parseMarketComparisonSummary({
      schemaVersion: 1,
      mode: "mark_price_pilot_v1",
      generatedAt: 1_780_000_000_000,
      refreshIntervalSeconds: 300,
      symbols: [
        {
          symbol: "BTCUSDT",
          status: "ready",
          coverage: { valid: 3, required: 3 },
          medianMarkPrice: 101,
          spreadPct: 1.98,
          sources: [source("bitget", 100), source("hyperliquid", 101), source("bybit", 102)]
        }
      ]
    });

    expect(summary).not.toBeNull();
    expect(findMarketComparisonItem(summary, "BTCUSDT")?.medianMarkPrice).toBe(101);
    expect(
      findMarketComparisonItem(summary, "BTCUSDT")?.sources.find(
        (item) => item.source === "hyperliquid"
      )?.quote
    ).toBe("USDT");
  });

  it("accepts incomplete coverage only without a median", () => {
    const summary = parseMarketComparisonSummary({
      schemaVersion: 1,
      mode: "mark_price_pilot_v1",
      generatedAt: 1,
      refreshIntervalSeconds: 300,
      symbols: [
        {
          symbol: "BTCUSDT",
          status: "incomplete",
          coverage: { valid: 2, required: 3 },
          medianMarkPrice: null,
          spreadPct: null,
          sources: [
            source("bitget", 100),
            {
              source: "hyperliquid",
              status: "unavailable",
              sourceSymbol: null,
              quote: null,
              markPrice: null,
              observedAt: null,
              sourceAt: null,
              error: "TimeoutError"
            },
            source("bybit", 102)
          ]
        }
      ]
    });

    expect(findMarketComparisonItem(summary, "BTCUSDT")?.medianMarkPrice).toBeNull();
  });

  it("rejects coverage that disagrees with the source rows", () => {
    expect(
      parseMarketComparisonSummary({
        schemaVersion: 1,
        mode: "mark_price_pilot_v1",
        generatedAt: 1,
        refreshIntervalSeconds: 300,
        symbols: [
          {
            symbol: "BTCUSDT",
            status: "ready",
            coverage: { valid: 3, required: 3 },
            medianMarkPrice: 101,
            spreadPct: 1.98,
            sources: [
              source("bitget", 100),
              { ...source("hyperliquid", 101), status: "unavailable", markPrice: null },
              source("bybit", 102)
            ]
          }
        ]
      })?.symbols
    ).toEqual([]);
  });
});
