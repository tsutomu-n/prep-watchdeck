import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import type {
  DashboardRawSortKey,
  DashboardRawSortState,
  DashboardRankingTimeframe
} from "$lib/market/dashboard-filters";

export type RawSortValue = number | null;

const dataQualityScore: Record<string, number> = {
  OK: 3,
  PARTIAL: 2,
  STALE: 1,
  MISSING: 0
};

export function sortRowsByRawSort(
  rows: readonly ScannerRowDTO[],
  state: DashboardRawSortState,
  timeframe: DashboardRankingTimeframe
): ScannerRowDTO[] {
  return rows
    .map((row, index) => ({ row, index, value: getRawSortValue(row, state, timeframe) }))
    .sort((left, right) => {
      const leftMissing = left.value === null;
      const rightMissing = right.value === null;
      if (leftMissing && rightMissing) return left.index - right.index;
      if (leftMissing) return 1;
      if (rightMissing) return -1;
      const leftValue = left.value ?? 0;
      const rightValue = right.value ?? 0;
      if (leftValue === rightValue) return left.index - right.index;
      return state.direction === "asc" ? leftValue - rightValue : rightValue - leftValue;
    })
    .map((item) => item.row);
}

export function getRawSortValue(
  row: ScannerRowDTO,
  state: DashboardRawSortState,
  timeframe: DashboardRankingTimeframe
): RawSortValue {
  switch (state.sortKey) {
    case "changePct":
      return numberOrNull(row.changePctByTf?.[timeframe]);
    case "turnoverUsdt":
      return numberOrNull(row.turnoverUsdtByTf?.[timeframe]);
    case "volumeRatio":
      return numberOrNull(row.volumeRatioByTf?.[timeframe]);
    case "attentionScore":
      return numberOrNull(row.attentionScore);
    case "riskTagCount":
      return numberOrNull(row.riskTagCodes?.length ?? 0);
    case "dataQuality":
      return numberOrNull(dataQualityScore[row.dataQuality]);
  }
}

export function rawSortLabel(
  state: DashboardRawSortState,
  timeframe: DashboardRankingTimeframe,
  labels: {
    sortKeyLabel: (sortKey: DashboardRawSortKey) => string;
    directionLabel: (direction: DashboardRawSortState["direction"]) => string;
  }
) {
  return `${timeframe} ${labels.sortKeyLabel(state.sortKey)} ${labels.directionLabel(state.direction)}`;
}

export function rawSortHasTimeframeData(row: ScannerRowDTO, timeframe: DashboardRankingTimeframe) {
  return row.changePctByTf?.[timeframe] !== undefined || row.turnoverUsdtByTf?.[timeframe] !== undefined;
}

function numberOrNull(value: unknown): RawSortValue {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
