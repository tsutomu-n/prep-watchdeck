import { describe, expect, it } from "vitest";
import type { PrepWatchdeckScannerSnapshot, ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import { slimSnapshotForDashboard } from "./dashboard-snapshot";

describe("dashboard snapshot payload", () => {
  it("keeps dashboard rows while limiting embedded sparkline bars", () => {
    const source = snapshot({
      rows: [
        row({
          sparkline: {
            tf: "15m",
            points: Array.from({ length: 20 }, (_, index) => index),
            bars: Array.from({ length: 30 }, (_, index) => ({ close: index })),
            timeframes: {
              "15m": Array.from({ length: 40 }, (_, index) => ({ close: index })),
              "1h": Array.from({ length: 18 }, (_, index) => ({ close: index }))
            }
          }
        })
      ]
    });

    const slimmed = slimSnapshotForDashboard(source);
    const sparkline = slimmed.rows[0].sparkline as {
      tf: string;
      points: number[];
      bars: { close: number }[];
      timeframes: Record<string, { close: number }[]>;
    };

    expect(slimmed.rows).toHaveLength(1);
    expect(sparkline.tf).toBe("15m");
    expect(sparkline.points).toEqual(Array.from({ length: 16 }, (_, index) => index + 4));
    expect(sparkline.bars).toHaveLength(16);
    expect(sparkline.bars[0].close).toBe(14);
    expect(sparkline.timeframes["15m"]).toHaveLength(16);
    expect(sparkline.timeframes["15m"][0].close).toBe(24);
    expect(sparkline.timeframes["1h"]).toHaveLength(16);
    expect(sparkline.timeframes["1h"][0].close).toBe(2);
  });

  it("does not mutate the cached source snapshot", () => {
    const source = snapshot({
      rows: [
        row({
          sparkline: {
            bars: Array.from({ length: 30 }, (_, index) => ({ close: index }))
          }
        })
      ]
    });

    const slimmed = slimSnapshotForDashboard(source);

    expect((source.rows[0].sparkline as { bars: unknown[] }).bars).toHaveLength(30);
    expect((slimmed.rows[0].sparkline as { bars: unknown[] }).bars).toHaveLength(16);
  });

  it("returns the producer snapshot unchanged when every embedded series is already thin", () => {
    const sparkline = {
      tf: "5m",
      points: [1, 2, 3],
      bars: [{ close: 1 }, { close: 2 }],
      timeframes: {
        "15m": [{ close: 10 }, { close: 20 }]
      }
    };
    const source = snapshot({ rows: [row({ sparkline })] });

    const slimmed = slimSnapshotForDashboard(source);

    expect(slimmed).toBe(source);
    expect(slimmed.rows).toBe(source.rows);
    expect(slimmed.rows[0].sparkline).toBe(sparkline);
  });
});

function snapshot(overrides: Partial<PrepWatchdeckScannerSnapshot> = {}): PrepWatchdeckScannerSnapshot {
  return {
    schemaVersion: 1,
    engineVersion: "test",
    featureVersion: "test",
    rulesetVersion: "test",
    configHash: "test",
    runId: "test",
    generatedAt: 1,
    dataAsOf: 1,
    snapshotStatus: "OK",
    source: {
      exchange: "bitget",
      productType: "USDT-FUTURES",
      templateName: "balanced",
      dataSource: "fixture",
      isFallback: false,
      fixtureSet: "basic"
    },
    summary: {},
    rankings: {},
    rows: [],
    ...overrides
  };
}

function row(overrides: Partial<ScannerRowDTO> = {}): ScannerRowDTO {
  return {
    symbol: "ALTUSDT",
    ts: 1,
    category: "WATCH",
    label: "VOLUME_CONFIRMED_UP",
    attentionScore: 10,
    changePctByTf: {},
    turnoverUsdtByTf: {},
    dataQuality: "OK",
    reasonCodes: [],
    riskTagCodes: [],
    ...overrides
  };
}
