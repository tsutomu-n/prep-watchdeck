import { describe, expect, it } from "vitest";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import {
  miniSparklineData,
  miniSparklineDirection,
  miniSparklinePath,
  miniVolumeBars
} from "./mini-sparkline";

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

describe("mini sparkline helpers", () => {
  it("uses selected timeframe bars before generic bars", () => {
    const path = miniSparklinePath(
      scannerRow({
        sparkline: {
          bars: [
            { close: 1 },
            { close: 2 }
          ],
          timeframes: {
            "15m": [
              { close: 10 },
              { close: 20 }
            ]
          }
        }
      }),
      "15m"
    );

    expect(path).toBe("M0.0 22.0 L72.0 0.0");
  });

  it("falls back to point payloads when bars are missing", () => {
    expect(
      miniSparklinePath(
        scannerRow({
          sparkline: { points: [3, 6, 9] }
        }),
        "15m"
      )
    ).toBe("M0.0 22.0 L36.0 11.0 L72.0 0.0");
  });

  it("builds volume classes and heights from selected timeframe bars", () => {
    expect(
      miniVolumeBars(
        scannerRow({
          sparkline: {
            timeframes: {
              "15m": [
                { open: 2, close: 3, quoteVolume: 10 },
                { open: 3, close: 4, quoteVolume: 10 },
                { open: 4, close: 3, quoteVolume: 40 }
              ]
            }
          }
        }),
        "15m"
      )
    ).toEqual([
      { className: "volume-bar up normal", height: 3 },
      { className: "volume-bar up normal", height: 3 },
      { className: "volume-bar down strong", height: 12 }
    ]);
  });

  it("returns flat direction when no path exists", () => {
    expect(miniSparklineDirection(scannerRow({ changePctByTf: { "15m": 4 } }), "15m")).toBe("flat");
  });

  it("uses selected timeframe change for direction when a path exists", () => {
    const row = scannerRow({
      changePctByTf: { "15m": -1 },
      sparkline: {
        timeframes: {
          "15m": [
            { close: 2 },
            { close: 1 }
          ]
        }
      }
    });

    expect(miniSparklineDirection(row, "15m")).toBe("down");
  });

  it("reuses derived data for the same immutable row and timeframe", () => {
    const row = scannerRow({
      changePctByTf: { "15m": 1 },
      sparkline: {
        timeframes: {
          "15m": [
            { open: 1, close: 2, quoteVolume: 10 },
            { open: 2, close: 3, quoteVolume: 20 }
          ]
        }
      }
    });

    expect(miniSparklineData(row, "15m")).toBe(miniSparklineData(row, "15m"));
    expect(miniSparklineData(row, "1h")).not.toBe(miniSparklineData(row, "15m"));
  });
});
