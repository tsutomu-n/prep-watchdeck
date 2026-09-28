import type { LogicalRange, Time } from "lightweight-charts";
import type { ChartCandle } from "./chart-history";

export const CHART_TIME_ZONE = "Asia/Tokyo";
export const INITIAL_VISIBLE_BARS = 120;

const timeFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: CHART_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false
});
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: CHART_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit"
});
const monthFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: CHART_TIME_ZONE,
  year: "numeric",
  month: "2-digit"
});
const dayFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: CHART_TIME_ZONE,
  month: "2-digit",
  day: "2-digit"
});
const yearFormat = new Intl.DateTimeFormat("ja-JP", {
  timeZone: CHART_TIME_ZONE,
  year: "numeric"
});

export function chartTimeMs(time: Time) {
  if (typeof time === "number") return time * 1000;
  if (typeof time === "string") return Date.parse(time);
  return Date.UTC(time.year, time.month - 1, time.day);
}

export function formatChartTime(time: Time) {
  const date = new Date(chartTimeMs(time));
  return `${dateFormat.format(date)} ${timeFormat.format(date)} JST`;
}

export function formatChartTick(time: Time, part: "year" | "month" | "day" | "time") {
  const format = { year: yearFormat, month: monthFormat, day: dayFormat, time: timeFormat }[part];
  return format.format(new Date(chartTimeMs(time)));
}

export function mergeChartBars(existing: ChartCandle[], incoming: ChartCandle[]) {
  const byTime = new Map(existing.map((bar) => [bar.bucketAt, bar]));
  for (const bar of incoming) byTime.set(bar.bucketAt, bar);
  return [...byTime.values()].sort((left, right) => Date.parse(left.bucketAt) - Date.parse(right.bucketAt));
}

// Logical indices move when older candles are prepended. Preserve the same bars and
// fractional zoom; only advance a viewport that was already following the latest bar.
export function chartRangeAfterUpdate(
  previous: ChartCandle[],
  next: ChartCandle[],
  range: LogicalRange | null
): { from: number; to: number } | null {
  if (next.length === 0) return null;
  if (!range || previous.length === 0) {
    return { from: Math.max(0, next.length - INITIAL_VISIBLE_BARS), to: next.length - 1 + 3 };
  }
  const lastPrevious = previous[previous.length - 1].bucketAt;
  const anchor = next.findIndex((bar) => bar.bucketAt === lastPrevious);
  if (anchor < 0) return { from: Number(range.from), to: Number(range.to) };
  const shift = range.to >= previous.length - 1
    ? next.length - previous.length
    : anchor - (previous.length - 1);
  return { from: range.from + shift, to: range.to + shift };
}
