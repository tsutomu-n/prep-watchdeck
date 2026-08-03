import { describe, expect, it } from "vitest";
import type { UTCTimestamp } from "lightweight-charts";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import {
  buildChartAccessibleSummary,
  buildChartData,
  buildChartDataFromPayload,
  buildLineData,
  buildVolumeData,
  timeframeSeconds
} from "./chart-data";

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

function candle(ts: number, open: number, high: number, low: number, close: number, quoteVolume: number) {
  return { ts, open, high, low, close, quoteVolume };
}

describe("chart data helpers", () => {
  it("uses selected timeframe bars before generic bars without aggregating them", () => {
    expect(
      buildChartData(
        scannerRow({
          sparkline: {
            bars: [candle(60_000, 1, 3, 1, 2, 10)],
            timeframes: {
              "15m": [candle(120_000, 10, 14, 9, 12, 100)]
            }
          }
        }),
        "15m"
      )
    ).toMatchObject([{ time: 120, open: 10, high: 14, low: 9, close: 12, quoteVolume: 100 }]);
  });

  it("aggregates generic bars into the selected timeframe", () => {
    expect(
      buildChartData(
        scannerRow({
          sparkline: {
            bars: [
              candle(60_000, 10, 12, 9, 11, 10),
              candle(300_000, 11, 13, 8, 12, 15),
              candle(1_200_000, 20, 21, 19, 20.5, 30)
            ]
          }
        }),
        "15m"
      )
    ).toMatchObject([
      { time: 0, open: 10, high: 13, low: 8, close: 12, quoteVolume: 25 },
      { time: 900, open: 20, high: 21, low: 19, close: 20.5, quoteVolume: 30 }
    ]);
  });

  it("rejects invalid candle payloads and caps chart bars", () => {
    const bars = Array.from({ length: 130 }, (_, index) => candle((index + 1) * 60_000, 1, 2, 0.5, 1.5, 1));

    expect(
      buildChartData(
        scannerRow({
          sparkline: {
            timeframes: {
              "5m": [{ ts: 60_000, open: 0, high: 2, low: 1, close: 1, quoteVolume: 1 }, ...bars]
            }
          }
        }),
        "5m"
      )
    ).toHaveLength(128);
  });

  it("builds volume colors from candle direction", () => {
    const palette = { up: "chart-volume-up", down: "chart-volume-down" };

    expect(
      buildVolumeData([
        { time: 60 as UTCTimestamp, open: 1, high: 2, low: 1, close: 2, quoteVolume: 10 },
        { time: 120 as UTCTimestamp, open: 2, high: 2, low: 1, close: 1, quoteVolume: 20 }
      ], palette)
    ).toEqual([
      { time: 60, value: 10, color: "chart-volume-up" },
      { time: 120, value: 20, color: "chart-volume-down" }
    ]);
  });

  it("builds a concise accessible OHLCV summary for candle data", () => {
    expect(
      buildChartAccessibleSummary(
        "ALT",
        "15m",
        [
          { time: 1_700_000_000 as UTCTimestamp, open: 10, high: 12, low: 9, close: 11, quoteVolume: 800 },
          {
            time: 1_700_000_900 as UTCTimestamp,
            open: 11,
            high: 13,
            low: 10.5,
            close: 12.5,
            quoteVolume: 1_000
          }
        ],
        []
      )
    ).toBe(
      "ALT 15m足。ローソク足2本。期間 2023-11-14 22:13:20 UTC から 2023-11-14 22:28:20 UTC。最新足は始値 11、高値 13、安値 10.5、終値 12.5、出来高 1,000。"
    );
  });

  it("describes line-only and empty chart states without fabricating OHLCV", () => {
    expect(
      buildChartAccessibleSummary("ALT", "15m", [], [
        { time: 1_700_000_000 as UTCTimestamp, value: 10 },
        { time: 1_700_000_900 as UTCTimestamp, value: 12.5 }
      ])
    ).toBe(
      "ALT 15m足。価格推移2点。期間 2023-11-14 22:13:20 UTC から 2023-11-14 22:28:20 UTC。最新値は 12.5。"
    );
    expect(buildChartAccessibleSummary("ALT", "15m", [], [])).toBe(
      "ALT 15m足。表示できる価格データはありません。"
    );
  });

  it("uses separate chart payload bars without row sparkline bars", () => {
    expect(
      buildChartDataFromPayload(
        {
          timeframes: {
            "15m": [candle(120_000, 10, 14, 9, 12, 100)]
          }
        },
        "15m"
      )
    ).toMatchObject([{ time: 120, open: 10, high: 14, low: 9, close: 12, quoteVolume: 100 }]);
  });

  it("builds fallback line timestamps from row timestamp and timeframe", () => {
    expect(
      buildLineData(
        scannerRow({
          ts: 1_000_000,
          sparkline: { points: [10, "bad", 20, 30] }
        }),
        "5m"
      )
    ).toEqual([
      { time: 400, value: 10 },
      { time: 700, value: 20 },
      { time: 1000, value: 30 }
    ]);
  });

  it("keeps the established timeframe second mapping", () => {
    expect(timeframeSeconds("5m")).toBe(300);
    expect(timeframeSeconds("15m")).toBe(900);
    expect(timeframeSeconds("1h")).toBe(3600);
    expect(timeframeSeconds("4h")).toBe(14400);
    expect(timeframeSeconds("24h")).toBe(86400);
    expect(timeframeSeconds("74h")).toBe(266400);
    expect(timeframeSeconds("unknown")).toBe(900);
  });
});
