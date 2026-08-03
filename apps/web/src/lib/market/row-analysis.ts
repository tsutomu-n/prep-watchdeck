import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";

type CandlePayload = {
  high?: unknown;
  low?: unknown;
  close?: unknown;
};

type SparklinePayload = {
  bars?: unknown[];
  timeframes?: Record<string, unknown[]>;
};

export type MovementSignal = {
  label: string;
  shortLabel: string;
  tone: "up" | "down" | "warn" | "neutral";
};

export type Range24h = {
  low: number;
  high: number;
  close: number;
  positionPct: number;
  rangePct: number;
  bars: number;
};

export function movementSignals(row: ScannerRowDTO, selectedTimeframe: string): MovementSignal[] {
  const change5m = row.changePctByTf?.["5m"];
  const change15m = row.changePctByTf?.["15m"];
  const change1h = row.changePctByTf?.["1h"];
  const change24h = row.changePctByTf?.["24h"];
  const dir5m = direction(change5m);
  const dir15m = direction(change15m);
  const dir1h = direction(change1h);
  const dir24h = direction(change24h, 0.2);
  const signals: MovementSignal[] = [];
  const has24hDivergence = dir24h !== "flat" && dir24h !== "unknown" && isOpposite(dir5m, dir24h);
  const has15mDivergence = dir15m !== "flat" && dir15m !== "unknown" && isOpposite(dir5m, dir15m);

  if (!has24hDivergence && !has15mDivergence && dir5m !== "flat" && dir5m !== "unknown" && dir5m === dir1h) {
    signals.push({
      label: "5分/1時間一致",
      shortLabel: "一致",
      tone: dir5m === "up" ? "up" : "down"
    });
  }
  if (has24hDivergence) {
    signals.push({ label: "短期逆行", shortLabel: "逆行", tone: "warn" });
  } else if (has15mDivergence) {
    signals.push({ label: "直近失速", shortLabel: "失速", tone: "warn" });
  }
  if (typeof change5m === "number" && Math.abs(change5m) >= 2) {
    signals.push({ label: "5分急変", shortLabel: "急変", tone: "warn" });
  }
  const selectedVolumeRatio = row.volumeRatioByTf?.[selectedTimeframe];
  if (typeof selectedVolumeRatio === "number" && selectedVolumeRatio >= 2) {
    signals.push({ label: "出来高増", shortLabel: "量増", tone: "neutral" });
  }

  return signals.slice(0, 4);
}

export function range24h(row: ScannerRowDTO): Range24h | null {
  const fieldHigh = finiteNumber(row.range24hHigh);
  const fieldLow = finiteNumber(row.range24hLow);
  const fieldPosition = finiteNumber(row.range24hPositionPct);
  const fieldRangePct = finiteNumber(row.range24hPct);
  const fieldClose = finiteNumber(row.lastPrice ?? row.analysisPrice);
  if (
    fieldHigh !== null &&
    fieldLow !== null &&
    fieldPosition !== null &&
    fieldRangePct !== null &&
    fieldClose !== null &&
    fieldHigh > 0 &&
    fieldLow > 0
  ) {
    return {
      high: fieldHigh,
      low: fieldLow,
      close: fieldClose,
      positionPct: clampPct(fieldPosition),
      rangePct: fieldRangePct,
      bars: 0
    };
  }

  const sparkline = row.sparkline as SparklinePayload | null | undefined;
  const rawBars = (sparkline?.bars ?? []).slice(-288);
  const bars = rawBars.map(toRangeBar).filter(isRangeBar);
  const sourceBars =
    bars.length >= 2 ? bars : (sparkline?.timeframes?.["24h"] ?? []).slice(-1).map(toRangeBar).filter(isRangeBar);
  if (sourceBars.length === 0) return null;

  const low = Math.min(...sourceBars.map((bar) => bar.low));
  const high = Math.max(...sourceBars.map((bar) => bar.high));
  const close = sourceBars[sourceBars.length - 1].close;
  if (high <= low) {
    return { low, high, close, positionPct: 50, rangePct: 0, bars: sourceBars.length };
  }
  return {
    low,
    high,
    close,
    positionPct: clampPct(((close - low) / (high - low)) * 100),
    rangePct: (high / low - 1) * 100,
    bars: sourceBars.length
  };
}

function finiteNumber(value: unknown) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

function direction(value: number | null | undefined, threshold = 0.05) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "unknown";
  if (value > threshold) return "up";
  if (value < -threshold) return "down";
  return "flat";
}

function isOpposite(left: string, right: string) {
  return (left === "up" && right === "down") || (left === "down" && right === "up");
}

function clampPct(value: number) {
  return Math.max(0, Math.min(100, value));
}

function toRangeBar(bar: unknown) {
  const candle = bar as CandlePayload | null | undefined;
  return {
    high: finiteNumber(candle?.high),
    low: finiteNumber(candle?.low),
    close: finiteNumber(candle?.close)
  };
}

function isRangeBar(bar: ReturnType<typeof toRangeBar>): bar is { high: number; low: number; close: number } {
  return (
    bar.high !== null &&
    bar.low !== null &&
    bar.close !== null &&
    bar.high > 0 &&
    bar.low > 0 &&
    bar.close > 0
  );
}
