import { describe, expect, test } from "vitest";
import type { LogicalRange, UTCTimestamp } from "lightweight-charts";
import type { ChartCandle } from "./chart-history";
import { chartRangeAfterUpdate, formatChartTick, formatChartTime, mergeChartBars } from "./chart-view";

describe("chart viewport", () => {
  const old = [bar(1), bar(2), bar(3), bar(4)];

  test("retains fractional zoom for identical data and corrections", () => {
    const range = { from: 0.25, to: 2.5 } as LogicalRange;
    expect(chartRangeAfterUpdate(old, old.map((item) => ({ ...item, close: 2 })), range))
      .toEqual(range);
  });

  test("keeps historical candles in view across prepends and latest updates", () => {
    const next = [bar(-1), bar(0), ...old, bar(5)];
    expect(chartRangeAfterUpdate(old, next, { from: 0.25, to: 2.5 } as LogicalRange))
      .toEqual({ from: 2.25, to: 4.5 });
    expect(chartRangeAfterUpdate(old, next, { from: 1.25, to: 4.5 } as LogicalRange))
      .toEqual({ from: 4.25, to: 7.5 });
  });

  test("starts with 120 candles rather than squeezing all history into the width", () => {
    expect(chartRangeAfterUpdate([], Array.from({ length: 500 }, (_, index) => bar(index)), null))
      .toEqual({ from: 380, to: 502 });
  });

  test("merges overlapping pages in order and accepts corrections without duplicate times", () => {
    const corrected = { ...bar(2), close: 2 };
    expect(mergeChartBars(old, [corrected, bar(0), bar(5)]))
      .toEqual([bar(0), bar(1), corrected, bar(3), bar(4), bar(5)]);
  });
});

test("chart times use JST across UTC midnight and daily candle boundaries", () => {
  expect(formatChartTime((Date.parse("2026-09-09T23:00:00Z") / 1000) as UTCTimestamp))
    .toBe("2026/09/10 08:00 JST");
  expect(formatChartTick((Date.parse("2026-09-09T23:00:00Z") / 1000) as UTCTimestamp, "day"))
    .toBe("09/10");
  expect(formatChartTime("2026-09-10")).toBe("2026/09/10 09:00 JST");
});

function bar(index: number): ChartCandle {
  return {
    bucketAt: new Date(Date.UTC(2026, 8, 10) + index * 300_000).toISOString(),
    open: 1, high: 2, low: 1, close: 1,
    volumeBase: 1, volumeNotional: null, complete: true
  };
}
