import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";

type SparklinePayload = {
  points?: unknown[];
  bars?: unknown[];
  timeframes?: Record<string, unknown[]>;
};

type CandlePayload = {
  open?: unknown;
  close?: unknown;
  quoteVolume?: unknown;
};

export type MiniVolumeBar = {
  className: string;
  height: number;
};

export type MiniSparklineData = {
  path: string;
  volumeBars: MiniVolumeBar[];
  direction: "up" | "down" | "flat";
};

const miniSparklineCache = new WeakMap<object, Map<string, MiniSparklineData>>();

export function miniSparklineData(
  row: ScannerRowDTO,
  selectedTimeframe: string
): MiniSparklineData {
  const cachedByTimeframe = miniSparklineCache.get(row);
  const cached = cachedByTimeframe?.get(selectedTimeframe);
  if (cached) return cached;

  const bars = miniTimeframeBars(row, selectedTimeframe);
  const path = sparklinePathFromValues(miniSparklineValues(row, bars));
  const change = row.changePctByTf?.[selectedTimeframe] ?? 0;
  const result: MiniSparklineData = {
    path,
    volumeBars: miniVolumeBarsFromSource(bars),
    direction: !path ? "flat" : change > 0 ? "up" : change < 0 ? "down" : "flat"
  };
  const nextCache = cachedByTimeframe ?? new Map<string, MiniSparklineData>();
  nextCache.set(selectedTimeframe, result);
  if (!cachedByTimeframe) miniSparklineCache.set(row, nextCache);
  return result;
}

export function miniSparklinePath(row: ScannerRowDTO, selectedTimeframe: string) {
  return miniSparklineData(row, selectedTimeframe).path;
}

function sparklinePathFromValues(values: number[]) {
  if (values.length < 2) return "";

  const width = 72;
  const height = 22;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export function miniVolumeBars(row: ScannerRowDTO, selectedTimeframe: string): MiniVolumeBar[] {
  return miniSparklineData(row, selectedTimeframe).volumeBars;
}

function miniVolumeBarsFromSource(sourceBars: unknown[]): MiniVolumeBar[] {
  const bars = sourceBars
    .map((bar) => {
      const candle = bar as CandlePayload | null | undefined;
      return {
        open: Number(candle?.open),
        close: Number(candle?.close),
        volume: Number(candle?.quoteVolume)
      };
    })
    .filter((bar) => Number.isFinite(bar.volume) && bar.volume >= 0);
  if (bars.length === 0) return [];

  const maxVolume = Math.max(...bars.map((bar) => bar.volume), 1);
  const medianVolume = median(bars.map((bar) => bar.volume).filter((volume) => volume > 0));
  return bars.map((bar) => {
    const height = Math.max(2, Math.round((bar.volume / maxVolume) * 12));
    const direction = bar.close >= bar.open ? "up" : "down";
    const strength = medianVolume > 0 && bar.volume >= medianVolume * 2 ? "strong" : "normal";
    return {
      className: `volume-bar ${direction} ${strength}`,
      height
    };
  });
}

export function miniSparklineDirection(row: ScannerRowDTO, selectedTimeframe: string) {
  return miniSparklineData(row, selectedTimeframe).direction;
}

function miniSparklineValues(row: ScannerRowDTO, timeframeBars: unknown[]) {
  const sparkline = row.sparkline as SparklinePayload | null | undefined;
  const barValues = timeframeBars
    .map((bar) => Number((bar as CandlePayload | null | undefined)?.close))
    .filter((value) => Number.isFinite(value) && value > 0);
  if (barValues.length > 0) return barValues.slice(-16);

  return (
    sparkline?.points
      ?.map((point) => Number(point))
      .filter((value) => Number.isFinite(value) && value > 0) ?? []
  ).slice(-16);
}

function miniTimeframeBars(row: ScannerRowDTO, selectedTimeframe: string) {
  const sparkline = row.sparkline as SparklinePayload | null | undefined;
  return (sparkline?.timeframes?.[selectedTimeframe] ?? sparkline?.bars ?? []).slice(-16);
}

function median(values: number[]) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[middle];
  return (sorted[middle - 1] + sorted[middle]) / 2;
}
