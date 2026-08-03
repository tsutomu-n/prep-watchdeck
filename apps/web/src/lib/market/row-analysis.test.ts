import { describe, expect, it } from "vitest";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import { movementSignals, range24h } from "./row-analysis";

function scannerRow(overrides: Partial<ScannerRowDTO> = {}): ScannerRowDTO {
  return {
    symbol: "ALTUSDT",
    ts: 0,
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

describe("row analysis helpers", () => {
  it("summarizes aligned movement and selected-timeframe volume", () => {
    const signals = movementSignals(
      scannerRow({
        changePctByTf: { "5m": 1, "15m": 0.5, "1h": 1.2, "24h": 3 },
        volumeRatioByTf: { "15m": 2.5 }
      }),
      "15m"
    );

    expect(signals).toContainEqual({ label: "5分/1時間一致", shortLabel: "一致", tone: "up" });
    expect(signals).toContainEqual({ label: "出来高増", shortLabel: "量増", tone: "neutral" });
  });

  it("surfaces short-term divergence before generic alignment", () => {
    expect(
      movementSignals(
        scannerRow({
          changePctByTf: { "5m": -1.1, "15m": -0.8, "1h": -1.4, "24h": 2.5 }
        }),
        "15m"
      )
    ).toContainEqual({ label: "短期逆行", shortLabel: "逆行", tone: "warn" });
  });

  it("uses the canonical slowdown label for a 15-minute divergence", () => {
    expect(
      movementSignals(
        scannerRow({
          changePctByTf: { "5m": 1.1, "15m": -0.8, "1h": 0.9, "24h": 2.5 }
        }),
        "15m"
      )
    ).toContainEqual({ label: "直近失速", shortLabel: "失速", tone: "warn" });
  });

  it("keeps every current maximum signal with canonical short labels", () => {
    expect(
      movementSignals(
        scannerRow({
          changePctByTf: { "5m": -2.5, "15m": -1, "1h": -1.4, "24h": 3 },
          volumeRatioByTf: { "15m": 2.5 }
        }),
        "15m"
      )
    ).toEqual([
      { label: "短期逆行", shortLabel: "逆行", tone: "warn" },
      { label: "5分急変", shortLabel: "急変", tone: "warn" },
      { label: "出来高増", shortLabel: "量増", tone: "neutral" }
    ]);
  });

  it("uses explicit 24h range fields when present and clamps position", () => {
    expect(
      range24h(
        scannerRow({
          lastPrice: 12,
          range24hHigh: 14,
          range24hLow: 10,
          range24hPositionPct: 120,
          range24hPct: 40
        })
      )
    ).toEqual({
      high: 14,
      low: 10,
      close: 12,
      positionPct: 100,
      rangePct: 40,
      bars: 0
    });
  });

  it("falls back to sparkline bars when explicit range fields are missing", () => {
    const range = range24h(
      scannerRow({
        sparkline: {
          bars: [
            { high: 12, low: 10, close: 11 },
            { high: 14, low: 9, close: 13 }
          ]
        }
      })
    );

    expect(range).toMatchObject({
      high: 14,
      low: 9,
      close: 13,
      positionPct: 80,
      bars: 2
    });
    expect(range?.rangePct).toBeCloseTo(55.5556, 4);
  });
});
