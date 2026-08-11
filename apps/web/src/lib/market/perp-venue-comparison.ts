export type PerpVenueName = "bitget" | "hyperliquid";

export type PerpVenueSource = {
  venue: PerpVenueName;
  status: "ok" | "unavailable";
  sourceSymbol: string;
  quote: string;
  collateral: string;
  markPrice: number | null;
  fundingRate: number | null;
  fundingIntervalHours: number | null;
  fundingRatePerHour: number | null;
  openInterestBase: number | null;
  openInterestNotional: number | null;
  volume24hNotional: number | null;
  observedAt: number | null;
  sourceAt: number | null;
  error: string | null;
};

export type PerpVenueComparisonItem = {
  symbol: string;
  asset: string;
  status: "ready" | "partial" | "unavailable";
  markSpreadPct: number | null;
  sources: PerpVenueSource[];
};

export type PerpVenueComparisonSummary = {
  schemaVersion: 1;
  mode: "perp_venue_comparison_v1";
  generatedAt: number;
  refreshIntervalSeconds: number;
  items: PerpVenueComparisonItem[];
};

const venueNames = new Set<PerpVenueName>(["bitget", "hyperliquid"]);

export function parsePerpVenueComparisonSummary(
  value: unknown
): PerpVenueComparisonSummary | null {
  if (
    !isRecord(value) ||
    value.schemaVersion !== 1 ||
    value.mode !== "perp_venue_comparison_v1" ||
    !isNonNegativeSafeInteger(value.generatedAt) ||
    !isPositiveNumber(value.refreshIntervalSeconds) ||
    !Array.isArray(value.items)
  ) {
    return null;
  }
  return {
    schemaVersion: 1,
    mode: "perp_venue_comparison_v1",
    generatedAt: value.generatedAt,
    refreshIntervalSeconds: value.refreshIntervalSeconds,
    items: value.items.flatMap((item) => {
      const parsed = parseItem(item);
      return parsed ? [parsed] : [];
    })
  };
}

export function findPerpVenueComparisonItem(
  summary: PerpVenueComparisonSummary | null,
  symbol: string
): PerpVenueComparisonItem | null {
  return summary?.items.find((item) => item.symbol === symbol) ?? null;
}

function parseItem(value: unknown): PerpVenueComparisonItem | null {
  if (
    !isRecord(value) ||
    !isNonEmptyString(value.symbol) ||
    !isNonEmptyString(value.asset) ||
    (value.status !== "ready" && value.status !== "partial" && value.status !== "unavailable") ||
    !isNullableFiniteNumber(value.markSpreadPct) ||
    !Array.isArray(value.sources) ||
    value.sources.length !== 2
  ) {
    return null;
  }
  const sources = value.sources.flatMap((source) => {
    const parsed = parseSource(source);
    return parsed ? [parsed] : [];
  });
  if (
    sources.length !== 2 ||
    new Set(sources.map((source) => source.venue)).size !== 2 ||
    !sources.every((source) => venueNames.has(source.venue))
  ) {
    return null;
  }
  const validCount = sources.filter((source) => source.status === "ok").length;
  const expectedStatus = validCount === 2 ? "ready" : validCount === 1 ? "partial" : "unavailable";
  if (
    value.status !== expectedStatus ||
    (expectedStatus === "ready") !== (value.markSpreadPct !== null)
  ) {
    return null;
  }
  return {
    symbol: value.symbol,
    asset: value.asset,
    status: value.status,
    markSpreadPct: value.markSpreadPct,
    sources,
  };
}

function parseSource(value: unknown): PerpVenueSource | null {
  if (
    !isRecord(value) ||
    !venueNames.has(value.venue as PerpVenueName) ||
    (value.status !== "ok" && value.status !== "unavailable") ||
    !isNonEmptyString(value.sourceSymbol) ||
    !isNonEmptyString(value.quote) ||
    !isNonEmptyString(value.collateral) ||
    !isNullableFiniteNumber(value.markPrice) ||
    !isNullableFiniteNumber(value.fundingRate) ||
    !isNullablePositiveNumber(value.fundingIntervalHours) ||
    !isNullableFiniteNumber(value.fundingRatePerHour) ||
    !isNullableNonNegativeNumber(value.openInterestBase) ||
    !isNullableNonNegativeNumber(value.openInterestNotional) ||
    !isNullableNonNegativeNumber(value.volume24hNotional) ||
    !isNullableNonNegativeSafeInteger(value.observedAt) ||
    !isNullableNonNegativeSafeInteger(value.sourceAt) ||
    !(value.error === null || isNonEmptyString(value.error))
  ) {
    return null;
  }
  if (
    (value.status === "ok" &&
      (!isPositiveNumber(value.markPrice) || value.observedAt === null || value.error !== null)) ||
    (value.status === "unavailable" &&
      (value.markPrice !== null || value.observedAt !== null || value.sourceAt !== null || value.error === null))
  ) {
    return null;
  }
  return {
    venue: value.venue as PerpVenueName,
    status: value.status,
    sourceSymbol: value.sourceSymbol,
    quote: value.quote,
    collateral: value.collateral,
    markPrice: value.markPrice,
    fundingRate: value.fundingRate,
    fundingIntervalHours: value.fundingIntervalHours,
    fundingRatePerHour: value.fundingRatePerHour,
    openInterestBase: value.openInterestBase,
    openInterestNotional: value.openInterestNotional,
    volume24hNotional: value.volume24hNotional,
    observedAt: value.observedAt,
    sourceAt: value.sourceAt,
    error: value.error,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function isPositiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function isNullablePositiveNumber(value: unknown): value is number | null {
  return value === null || isPositiveNumber(value);
}

function isNullableFiniteNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNullableNonNegativeNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isNullableNonNegativeSafeInteger(value: unknown): value is number | null {
  return value === null || isNonNegativeSafeInteger(value);
}
