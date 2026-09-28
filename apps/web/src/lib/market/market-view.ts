import type { RankedRow } from "$lib/generated/ranking-response";

export type RankingSort =
  | "server" | "asset" | "referenceClose" | "returnPct" | "quoteTurnover"
  | "return15m" | "return1h" | "return24h" | "ratio15m" | "ratio1h" | "dayPosition";

export type RankingView = {
  search: string;
  venue: "all" | "bitget" | "hyperliquid" | "aster";
  includeUnranked: boolean;
  minRatio: number | null;
  ratioPeriod: "15m" | "1h";
  minDayPosition: number | null;
  maxDayPosition: number | null;
  sort: RankingSort;
  direction: "asc" | "desc";
};

export function rankingSortValue(row: RankedRow, sort: RankingSort): number | string | null {
  switch (sort) {
    case "server": return row.rank;
    case "asset": return row.asset;
    case "referenceClose": return row.referenceClose.status === "ready" ? row.referenceClose.value : null;
    case "returnPct": return row.returnPct;
    case "quoteTurnover": return row.quoteTurnover;
    case "return15m": return row.windows["15m"].returnPct;
    case "return1h": return row.windows["1h"].returnPct;
    case "return24h": return row.windows["24h"].returnPct;
    case "ratio15m": return row.turnoverRatios["15m"].value;
    case "ratio1h": return row.turnoverRatios["1h"].value;
    case "dayPosition": return row.dayRangePosition.value;
  }
}

export function filterSortRankingRows(rows: RankedRow[], view: RankingView) {
  const search = view.search.trim().toLocaleLowerCase("en-US");
  return rows.filter((row) =>
    (view.includeUnranked || row.rank !== null) &&
    (view.venue === "all" || row.venues.includes(view.venue)) &&
    (!search || [row.asset, row.reference?.symbol ?? "", ...row.originals.map((o) => o.symbol)]
      .some((value) => value.toLocaleLowerCase("en-US").includes(search))) &&
    (view.minRatio === null ||
      (row.turnoverRatios[view.ratioPeriod].status === "ready" &&
        row.turnoverRatios[view.ratioPeriod].value !== null &&
        row.turnoverRatios[view.ratioPeriod].value! >= view.minRatio!)) &&
    (view.minDayPosition === null ||
      (row.dayRangePosition.status === "ready" &&
        row.dayRangePosition.value !== null && row.dayRangePosition.value >= view.minDayPosition)) &&
    (view.maxDayPosition === null ||
      (row.dayRangePosition.status === "ready" &&
        row.dayRangePosition.value !== null && row.dayRangePosition.value <= view.maxDayPosition))
  ).toSorted((left, right) => {
    const a = rankingSortValue(left, view.sort);
    const b = rankingSortValue(right, view.sort);
    if (a === null || b === null) return a === b ? left.id.localeCompare(right.id) : a === null ? 1 : -1;
    const compared = typeof a === "string" && typeof b === "string"
      ? a.localeCompare(b, "ja-JP") : Number(a) - Number(b);
    return (view.direction === "desc" ? -compared : compared) || left.id.localeCompare(right.id);
  });
}
