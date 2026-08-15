import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";

export type VenueFilter = "all" | UniverseInstrumentArtifact["venue"];
export type CoverageFilter = "all" | "multi" | "single";
export type QualityFilter = "all" | UniverseInstrumentArtifact["quality"];

export type UniverseFilters = {
  search: string;
  venue: VenueFilter;
  coverage: CoverageFilter;
  quality: QualityFilter;
};

export function filterAndSortUniverse(
  items: UniverseInstrumentArtifact[],
  filters: UniverseFilters
) {
  const search = filters.search.trim().toLocaleUpperCase("en-US");
  const groupSizes = new Map<string, number>();
  for (const item of items) {
    if (item.active && item.groupId) {
      groupSizes.set(item.groupId, (groupSizes.get(item.groupId) ?? 0) + 1);
    }
  }
  return items
    .filter((item) => item.active)
    .filter((item) => filters.venue === "all" || item.venue === filters.venue)
    .filter((item) => filters.quality === "all" || item.quality === filters.quality)
    .filter((item) => {
      const coverage = item.groupId ? (groupSizes.get(item.groupId) ?? 0) : 0;
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
