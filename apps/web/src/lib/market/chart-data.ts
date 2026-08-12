import type { CandlestickData, HistogramData, LineData, UTCTimestamp } from "lightweight-charts";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";

type CandlePayload = {
  ts?: unknown;
  open?: unknown;
  high?: unknown;
  low?: unknown;
  close?: unknown;
  quoteVolume?: unknown;
};

export type ChartCandle = CandlestickData & {
  quoteVolume: number;
};

export type ChartVolumePalette = {
  up: string;
  down: string;
};

type SparklinePayload = {
  points?: unknown[];
  bars?: unknown[];
  timeframes?: Record<string, unknown[]>;
};

export function buildChartData(selected: ScannerRowDTO | null, timeframe: string): ChartCandle[] {
  if (!selected) return [];

  const sparkline = selected.sparkline as SparklinePayload | null | undefined;
  const sourceBars = sparkline?.timeframes?.[timeframe] ?? sparkline?.bars ?? [];
  return buildChartDataFromBars(sourceBars, timeframe, Boolean(sparkline?.timeframes?.[timeframe]));
}

export function buildChartDataFromPayload(payload: unknown, timeframe: string): ChartCandle[] {
  if (!payload || typeof payload !== "object") return [];
  const timeframes = (payload as { timeframes?: Record<string, unknown[]> }).timeframes;
  const sourceBars = timeframes?.[timeframe] ?? [];
  return buildChartDataFromBars(sourceBars, timeframe, true);
}

export function buildVolumeData(bars: ChartCandle[], palette: ChartVolumePalette): HistogramData[] {
  return bars.map((bar) => ({
    time: bar.time,
    value: bar.quoteVolume,
    color: bar.close >= bar.open ? palette.up : palette.down
  }));
}

export function buildChartAccessibleSummary(
  displaySymbol: string,
  timeframe: string,
  candles: ChartCandle[],
  linePoints: LineData[]
) {
  const context = `${displaySymbol || "銘柄未選択"} ${timeframe}足`;
  const firstCandle = candles[0];
  const latestCandle = candles.at(-1);
  if (firstCandle && latestCandle) {
    return [
      `${context}。ローソク足${candles.length}本。`,
      `期間 ${formatChartTime(firstCandle.time)} から ${formatChartTime(latestCandle.time)}。`,
      `最新足は始値 ${formatChartNumber(latestCandle.open)}、高値 ${formatChartNumber(latestCandle.high)}、` +
        `安値 ${formatChartNumber(latestCandle.low)}、終値 ${formatChartNumber(latestCandle.close)}、` +
        `出来高 ${formatChartNumber(latestCandle.quoteVolume)}。`
    ].join("");
  }

  const firstPoint = linePoints[0];
  const latestPoint = linePoints.at(-1);
  if (firstPoint && latestPoint) {
    return (
      `${context}。価格推移${linePoints.length}点。` +
      `期間 ${formatChartTime(firstPoint.time)} から ${formatChartTime(latestPoint.time)}。` +
      `最新値は ${formatChartNumber(latestPoint.value)}。`
    );
  }

  return `${context}。表示できる価格データはありません。`;
}

export function buildLineData(selected: ScannerRowDTO | null, timeframe: string, nowMs = Date.now()): LineData[] {
  if (!selected) return [];

  const sparkline = selected.sparkline as SparklinePayload | null | undefined;
  const values =
    sparkline?.points
      ?.map((point) => Number(point))
      .filter((value) => Number.isFinite(value) && value > 0) ?? [];
  if (values.length === 0) return [];

  const endMs = Number(selected.ts);
  const intervalMs = timeframeSeconds(timeframe) * 1000;
  const baseMs = Number.isFinite(endMs) && endMs > 0 ? endMs : nowMs;
  return values.map((value, index) => ({
    time: Math.floor((baseMs - (values.length - 1 - index) * intervalMs) / 1000) as UTCTimestamp,
    value
  }));
}

export function timeframeSeconds(value: string) {
  if (value === "5m") return 5 * 60;
  if (value === "15m") return 15 * 60;
  if (value === "1h") return 60 * 60;
  if (value === "4h") return 4 * 60 * 60;
  if (value === "24h") return 24 * 60 * 60;
  return 15 * 60;
}

function toCandleData(value: unknown): ChartCandle | null {
  if (!value || typeof value !== "object") return null;

  const candidate = value as CandlePayload;
  const ts = Number(candidate.ts);
  const open = Number(candidate.open);
  const high = Number(candidate.high);
  const low = Number(candidate.low);
  const close = Number(candidate.close);
  const quoteVolume = Number(candidate.quoteVolume);

  if (
    ![ts, open, high, low, close].every((item) => Number.isFinite(item) && item > 0) ||
    !Number.isFinite(quoteVolume) ||
    quoteVolume < 0
  ) {
    return null;
  }

  return {
    time: Math.floor(ts / 1000) as UTCTimestamp,
    open,
    high,
    low,
    close,
    quoteVolume
  };
}

function buildChartDataFromBars(sourceBars: unknown[], timeframe: string, alreadyAggregated: boolean): ChartCandle[] {
  const bars = sourceBars
    .map(toCandleData)
    .filter((bar): bar is ChartCandle => bar !== null)
    .sort((left, right) => Number(left.time) - Number(right.time));
  if (alreadyAggregated) return bars.slice(-128);
  return aggregateByTimeframe(bars, timeframe).slice(-128);
}

function aggregateByTimeframe(bars: ChartCandle[], selectedTimeframe: string): ChartCandle[] {
  if (bars.length === 0) return [];

  const seconds = timeframeSeconds(selectedTimeframe);
  const grouped = new Map<number, ChartCandle>();
  for (const bar of bars) {
    const bucket = Math.floor(Number(bar.time) / seconds) * seconds;
    const current = grouped.get(bucket);
    if (!current) {
      grouped.set(bucket, {
        time: bucket as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
        quoteVolume: bar.quoteVolume
      });
      continue;
    }

    current.high = Math.max(current.high, bar.high);
    current.low = Math.min(current.low, bar.low);
    current.close = bar.close;
    current.quoteVolume += bar.quoteVolume;
  }

  return [...grouped.values()].sort((left, right) => Number(left.time) - Number(right.time));
}

function formatChartTime(time: ChartCandle["time"] | LineData["time"]) {
  if (typeof time === "number") {
    return new Date(time * 1000).toISOString().slice(0, 19).replace("T", " ") + " UTC";
  }
  if (typeof time === "string") return `${time} UTC`;
  return `${time.year}-${String(time.month).padStart(2, "0")}-${String(time.day).padStart(2, "0")} UTC`;
}

function formatChartNumber(value: number) {
  return new Intl.NumberFormat("ja-JP", { maximumSignificantDigits: 12 }).format(value);
}
