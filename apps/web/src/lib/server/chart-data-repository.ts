import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { resolveStatePaths } from "./state-paths";

export const dashboardTimeframes = ["5m", "15m", "1h", "4h", "24h"] as const;
export type DashboardTimeframe = (typeof dashboardTimeframes)[number];

export type ChartBarPayload = {
  ts: number;
  open: number;
  high: number;
  low: number;
  close: number;
  quoteVolume: number;
};

export type ChartDataPayload = {
  schemaVersion: 2;
  snapshotRunId: string;
  symbol: string;
  generatedAt: number;
  dataAsOf: number;
  timeframes: Partial<Record<DashboardTimeframe, ChartBarPayload[]>>;
};

export interface ChartDataRepository {
  symbol(
    symbol: string,
    timeframe: DashboardTimeframe,
    snapshotRunId: string
  ): Promise<ChartDataPayload | undefined>;
}

export class ChartDataValidationError extends Error {}
export class ChartRunMismatchError extends Error {}

type ChartCacheEntry = {
  size: bigint;
  mtimeNs: bigint;
  payload: ChartDataPayload;
};

const safeSymbolPattern = /^[A-Z0-9_-]+$/;
const chartCache = new Map<string, ChartCacheEntry>();

export class LocalFileChartDataRepository implements ChartDataRepository {
  constructor(private readonly chartDir = defaultChartDir()) {}

  async symbol(
    symbol: string,
    timeframe: DashboardTimeframe,
    snapshotRunId: string
  ): Promise<ChartDataPayload | undefined> {
    const normalized = symbol.toUpperCase();
    if (!safeSymbolPattern.test(normalized)) {
      throw new Error("invalid symbol");
    }

    const chartPath = resolve(this.chartDir, `${normalized}.json`);
    const metadata = await stat(chartPath, { bigint: true }).catch((cause) => {
      if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
        return null;
      }
      throw cause;
    });
    if (metadata === null) {
      chartCache.delete(chartPath);
      return undefined;
    }

    const cached = chartCache.get(chartPath);
    let payload: ChartDataPayload;
    if (cached && cached.size === metadata.size && cached.mtimeNs === metadata.mtimeNs) {
      payload = cached.payload;
    } else {
      const raw = await readFile(chartPath, "utf-8");
      let candidate: unknown;
      try {
        candidate = JSON.parse(raw);
      } catch {
        throw new ChartDataValidationError("invalid chart data");
      }
      payload = validateChartData(candidate, normalized);
      chartCache.set(chartPath, {
        size: metadata.size,
        mtimeNs: metadata.mtimeNs,
        payload
      });
    }
    if (payload.snapshotRunId !== snapshotRunId) {
      throw new ChartRunMismatchError("snapshot run mismatch");
    }
    return {
      ...payload,
      timeframes: {
        [timeframe]: payload.timeframes[timeframe] ?? []
      }
    };
  }
}

export function createChartDataRepository(): ChartDataRepository {
  return new LocalFileChartDataRepository();
}

export function isDashboardTimeframe(value: string): value is DashboardTimeframe {
  return dashboardTimeframes.some((timeframe) => timeframe === value);
}

export function isSafeChartSymbol(value: string): boolean {
  return safeSymbolPattern.test(value.toUpperCase());
}

function validateChartData(candidate: unknown, requestedSymbol: string): ChartDataPayload {
  if (!isRecord(candidate)) throw new ChartDataValidationError("invalid chart data");
  if (
    candidate.schemaVersion !== 2 ||
    typeof candidate.snapshotRunId !== "string" ||
    candidate.snapshotRunId.length === 0 ||
    candidate.symbol !== requestedSymbol ||
    !isNonNegativeInteger(candidate.generatedAt) ||
    !isNonNegativeInteger(candidate.dataAsOf) ||
    !isRecord(candidate.timeframes)
  ) {
    throw new ChartDataValidationError("invalid chart data");
  }

  const timeframes: Partial<Record<DashboardTimeframe, ChartBarPayload[]>> = {};
  for (const [timeframe, bars] of Object.entries(candidate.timeframes)) {
    if (!isDashboardTimeframe(timeframe) || !Array.isArray(bars) || bars.length > 128) {
      throw new ChartDataValidationError("invalid chart data");
    }
    const validatedBars = bars.map(validateChartBar);
    for (let index = 1; index < validatedBars.length; index += 1) {
      if (validatedBars[index - 1].ts >= validatedBars[index].ts) {
        throw new ChartDataValidationError("invalid chart data");
      }
    }
    timeframes[timeframe] = validatedBars;
  }

  return {
    schemaVersion: 2,
    snapshotRunId: candidate.snapshotRunId,
    symbol: candidate.symbol,
    generatedAt: candidate.generatedAt,
    dataAsOf: candidate.dataAsOf,
    timeframes
  };
}

function validateChartBar(candidate: unknown): ChartBarPayload {
  if (!isRecord(candidate)) throw new ChartDataValidationError("invalid chart data");
  const { ts, open, high, low, close, quoteVolume } = candidate;
  if (
    !isPositiveInteger(ts) ||
    !isPositiveNumber(open) ||
    !isPositiveNumber(high) ||
    !isPositiveNumber(low) ||
    !isPositiveNumber(close) ||
    !isNonNegativeNumber(quoteVolume)
  ) {
    throw new ChartDataValidationError("invalid chart data");
  }
  return { ts, open, high, low, close, quoteVolume };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function defaultChartDir() {
  return resolveStatePaths().chartDir;
}
