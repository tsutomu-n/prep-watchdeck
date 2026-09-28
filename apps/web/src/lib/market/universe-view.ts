import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import type { MarketMetricRow } from "$lib/generated/market-metrics";

export type VenueFilter = "all" | UniverseInstrumentArtifact["venue"];
export type CoverageFilter = "all" | "multi" | "single";
export type QualityFilter = "all" | UniverseInstrumentArtifact["quality"];
export type NativeSort = "base" | "funding" | "spread" | "oi15m" | "oi1h" |
  "trade15m" | "trade1h" | "trade24h";

export function sortNativeRows(
  items: UniverseInstrumentArtifact[], sort: NativeSort, direction: "asc" | "desc",
  metricFor: (item: UniverseInstrumentArtifact) => MarketMetricRow | null,
  now: number
) {
  if (sort === "base") return items;
  const value = (item: UniverseInstrumentArtifact): number | null => {
    const row = metricFor(item);
    const metric = sort === "oi15m" ? row?.oiChange["15m"] :
      sort === "oi1h" ? row?.oiChange["1h"] :
      sort === "trade15m" ? row?.tradeChange["15m"] :
      sort === "trade1h" ? row?.tradeChange["1h"] :
      sort === "trade24h" ? row?.tradeChange["24h"] : null;
    if (sort === "funding" || sort === "spread") {
      const observed = item.observedAt ? Date.parse(item.observedAt) : Number.NaN;
      const source = item.sourceAt ? Date.parse(item.sourceAt) : observed;
      if (!Number.isFinite(observed) || !Number.isFinite(source) ||
          observed > now || source > now || now - observed > 120_000 || now - source > 120_000) {
        return null;
      }
      return sort === "funding" ? item.fundingRatePerHour : spreadBps(item.bestBid, item.bestAsk);
    }
    const end = metric?.endAt ? Date.parse(metric.endAt) : Number.NaN;
    const source = metric?.endSourceAt ? Date.parse(metric.endSourceAt) : end;
    const maxAge = sort.startsWith("oi") ? 120_000 : 300_000;
    return metric?.availability === "available" && Number.isFinite(end) &&
      Number.isFinite(source) && end <= now && source <= now &&
      now - end <= maxAge && now - source <= maxAge ? metric.value : null;
  };
  return items.toSorted((a, b) => {
    const left = value(a); const right = value(b);
    if (left === null || right === null || !Number.isFinite(left) || !Number.isFinite(right)) {
      const missingLeft = left === null || !Number.isFinite(left);
      const missingRight = right === null || !Number.isFinite(right);
      return missingLeft === missingRight ? a.venueInstrumentId.localeCompare(b.venueInstrumentId)
        : missingLeft ? 1 : -1;
    }
    return (direction === "asc" ? left - right : right - left) ||
      a.venueInstrumentId.localeCompare(b.venueInstrumentId);
  });
}

export type UniverseFilters = {
  search: string;
  venue: VenueFilter;
  coverage: CoverageFilter;
  quality: QualityFilter;
};

export function groupVenueCounts(items: UniverseInstrumentArtifact[]) {
  const venues = new Map<string, Set<UniverseInstrumentArtifact["venue"]>>();
  for (const item of items) {
    if (!item.active || !item.groupId) continue;
    const current = venues.get(item.groupId) ?? new Set<UniverseInstrumentArtifact["venue"]>();
    current.add(item.venue);
    venues.set(item.groupId, current);
  }
  return new Map([...venues].map(([groupId, values]) => [groupId, values.size]));
}

export function coverageLabel(
  item: UniverseInstrumentArtifact,
  counts: ReadonlyMap<string, number>
) {
  if (!item.groupId) return "未group";
  const count = counts.get(item.groupId) ?? 1;
  return count >= 2 ? `${count} Venue` : "単独";
}

export function filterAndSortUniverse(
  items: UniverseInstrumentArtifact[],
  filters: UniverseFilters
) {
  const search = filters.search.trim().toLocaleUpperCase("en-US");
  const groupSizes = groupVenueCounts(items);
  return items
    .filter((item) => item.active)
    .filter((item) => filters.venue === "all" || item.venue === filters.venue)
    .filter((item) => filters.quality === "all" || item.quality === filters.quality)
    .filter((item) => {
      const coverage = item.groupId ? (groupSizes.get(item.groupId) ?? 1) : 0;
      if (filters.coverage === "multi") return coverage >= 2;
      if (filters.coverage === "single") return coverage < 2;
      return true;
    })
    .filter((item) =>
      search
        ? [
            item.baseAsset,
            item.sourceSymbol,
            item.venueInstrumentId,
            item.quoteAsset,
            item.settleAsset
          ].some((value) => value.toLocaleUpperCase("en-US").includes(search))
        : true
    )
    .toSorted(
      (left, right) =>
        compareText(left.baseAsset, right.baseAsset) ||
        compareText(left.venue, right.venue) ||
        compareText(left.sourceSymbol, right.sourceSymbol)
    );
}

export function formatFinite(value: number | null | undefined, maximumFractionDigits = 6) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits }).format(value);
}

/** Preserve small, nonzero prices without treating the order tick as a mark-price increment. */
export function formatPrice(value: number | null | undefined, digits = 18) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  if (value !== 0 && Math.abs(value) < 1e-18) return value.toExponential(8);
  return new Intl.NumberFormat("ja-JP", { maximumFractionDigits: digits }).format(value);
}

export function formatBidAsk(bid: number | null | undefined, ask: number | null | undefined) {
  if (typeof bid !== "number" || typeof ask !== "number" ||
      !Number.isFinite(bid) || !Number.isFinite(ask) || bid === ask) {
    return [formatPrice(bid), formatPrice(ask)] as const;
  }
  for (let digits = 0; digits <= 18; digits += 1) {
    const left = formatPrice(bid, digits);
    const right = formatPrice(ask, digits);
    if (left !== right) return [left, right] as const;
  }
  return [bid.toExponential(8), ask.toExponential(8)] as const;
}

export function spreadBps(bid: number | null | undefined, ask: number | null | undefined) {
  if (typeof bid !== "number" || typeof ask !== "number" ||
      !Number.isFinite(bid) || !Number.isFinite(ask) || bid <= 0 || ask < bid) return null;
  const spread = 10_000 * (ask - bid) / ((ask + bid) / 2);
  return Number.isFinite(spread) ? spread : null;
}

export function formatCompact(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("ja-JP", {
    notation: "compact",
    maximumFractionDigits: 2
  }).format(value);
}

export function formatRate(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(5)}%`;
}

export function formatTimestamp(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "判定不能";
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false
  }).format(date);
}

function compareText(left: string, right: string) {
  return left.localeCompare(right, "en-US", { numeric: true, sensitivity: "base" });
}
