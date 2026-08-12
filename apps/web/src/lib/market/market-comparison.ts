export type MarketComparisonSourceName = "bitget" | "hyperliquid" | "bybit";

export type MarketComparisonSource = {
  source: MarketComparisonSourceName;
  status: "ok" | "unavailable";
  sourceSymbol: string | null;
  quote: string | null;
  markPrice: number | null;
  observedAt: number | null;
  sourceAt: number | null;
  error: string | null;
};

export type MarketComparisonItem = {
  symbol: string;
  status: "ready" | "incomplete";
  coverage: { valid: number; required: 3 };
  medianMarkPrice: number | null;
  spreadPct: number | null;
  sources: MarketComparisonSource[];
};

export type MarketComparisonSummary = {
  schemaVersion: 1;
  mode: "mark_price_pilot_v1";
  generatedAt: number;
  refreshIntervalSeconds: number;
  symbols: MarketComparisonItem[];
};

const sourceNames = new Set<MarketComparisonSourceName>(["bitget", "hyperliquid", "bybit"]);

export function parseMarketComparisonSummary(value: unknown): MarketComparisonSummary | null {
  if (
    !isRecord(value) ||
    value.schemaVersion !== 1 ||
    value.mode !== "mark_price_pilot_v1" ||
    !isNonNegativeSafeInteger(value.generatedAt) ||
    typeof value.refreshIntervalSeconds !== "number" ||
    !Number.isFinite(value.refreshIntervalSeconds) ||
    value.refreshIntervalSeconds <= 0 ||
    !Array.isArray(value.symbols)
  ) {
    return null;
  }
  return {
    schemaVersion: 1,
    mode: "mark_price_pilot_v1",
    generatedAt: value.generatedAt,
    refreshIntervalSeconds: value.refreshIntervalSeconds,
    symbols: value.symbols.flatMap((item) => {
      const parsed = parseMarketComparisonItem(item);
      return parsed ? [parsed] : [];
    })
  };
}

export function findMarketComparisonItem(
  summary: MarketComparisonSummary | null,
  symbol: string
): MarketComparisonItem | null {
  return summary?.symbols.find((item) => item.symbol === symbol) ?? null;
}

export function marketComparisonSourceLabel(source: MarketComparisonSourceName): string {
  return {
    bitget: "Bitget",
    hyperliquid: "Hyperliquid",
    bybit: "Bybit"
  }[source];
}

function parseMarketComparisonItem(value: unknown): MarketComparisonItem | null {
  if (
    !isRecord(value) ||
    typeof value.symbol !== "string" ||
    !/^[A-Z0-9_-]+$/.test(value.symbol) ||
    (value.status !== "ready" && value.status !== "incomplete") ||
    !isRecord(value.coverage) ||
    !isCoverageCount(value.coverage.valid) ||
    value.coverage.required !== 3 ||
    !isNullablePositiveNumber(value.medianMarkPrice) ||
    !isNullableNonNegativeNumber(value.spreadPct) ||
    !Array.isArray(value.sources)
  ) {
    return null;
  }
  const sources = value.sources.flatMap((item) => {
    const parsed = parseMarketComparisonSource(item);
    return parsed ? [parsed] : [];
  });
  if (sources.length !== 3 || new Set(sources.map((item) => item.source)).size !== 3) return null;
  const validSourceCount = sources.filter((item) => item.status === "ok").length;
  if (value.coverage.valid !== validSourceCount) return null;
  if (
    value.status === "ready" &&
    (validSourceCount !== 3 || value.medianMarkPrice === null || value.spreadPct === null)
  ) {
    return null;
  }
  if (
    value.status === "incomplete" &&
    (validSourceCount === 3 || value.medianMarkPrice !== null || value.spreadPct !== null)
  ) {
    return null;
  }
  return {
    symbol: value.symbol,
    status: value.status,
    coverage: { valid: value.coverage.valid, required: 3 },
    medianMarkPrice: value.medianMarkPrice,
    spreadPct: value.spreadPct,
    sources
  };
}

function parseMarketComparisonSource(value: unknown): MarketComparisonSource | null {
  if (
    !isRecord(value) ||
    typeof value.source !== "string" ||
    !sourceNames.has(value.source as MarketComparisonSourceName) ||
    (value.status !== "ok" && value.status !== "unavailable") ||
    !(value.sourceSymbol === null || typeof value.sourceSymbol === "string") ||
    !(value.quote === null || typeof value.quote === "string") ||
    !isNullablePositiveNumber(value.markPrice) ||
    !(value.observedAt === null || isNonNegativeSafeInteger(value.observedAt)) ||
    !(value.sourceAt === null || isNonNegativeSafeInteger(value.sourceAt)) ||
    !(value.error === null || typeof value.error === "string")
  ) {
    return null;
  }
  if (
    value.status === "ok" &&
    (value.sourceSymbol === null ||
      value.quote === null ||
      value.markPrice === null ||
      value.observedAt === null)
  ) {
    return null;
  }
  return {
    source: value.source as MarketComparisonSourceName,
    status: value.status,
    sourceSymbol: value.sourceSymbol,
    quote: value.quote,
    markPrice: value.markPrice,
    observedAt: value.observedAt,
    sourceAt: value.sourceAt,
    error: value.error
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isCoverageCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && typeof value === "number" && value >= 0 && value <= 3;
}

function isNullablePositiveNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value > 0);
}

function isNullableNonNegativeNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
}
