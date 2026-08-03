import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import type { DashboardRawSortState } from "$lib/market/dashboard-filters";

export const SMART_RANK_DEFAULT_TARGET_LIMIT = 20;
export const SMART_RANK_MAX_TARGET_LIMIT = 50;
export const SMART_RANK_COOLDOWN_MS = 30_000;

export type SmartRankBase = {
  smartRankRunId: string;
  createdAt: string;
  baseSnapshotRunId: string;
  timeframe: string;
  sortKey: string;
  sortDirection: "asc" | "desc";
  categoryFilter: string;
  viewFilter: string;
  targetLimit: number;
  targetSymbols: string[];
};

export type SmartRankRow = {
  row: ScannerRowDTO;
  sourceRank: number;
  smartScore: number;
  warningCount: number;
  qualityPenalty: number;
};

export type SmartRankState = {
  base: SmartRankBase;
  rows: SmartRankRow[];
  nextAllowedAtMs: number;
};

export type SmartRankInput = {
  rows: readonly ScannerRowDTO[];
  snapshotRunId: string;
  timeframe: string;
  rawSortState: DashboardRawSortState;
  categoryFilter: string;
  viewFilter: string;
  targetLimit: number | string;
  nowMs?: number;
  newId?: () => string;
};

export function normalizeSmartRankTargetLimit(value: number | string) {
  const parsed = typeof value === "number" ? value : Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return SMART_RANK_DEFAULT_TARGET_LIMIT;
  return Math.min(SMART_RANK_MAX_TARGET_LIMIT, Math.max(1, Math.trunc(parsed)));
}

export function canRunSmartRank({
  nowMs,
  state,
  availableRows
}: {
  nowMs: number;
  state: SmartRankState | null;
  availableRows: number;
}) {
  if (availableRows <= 0) return false;
  return !state || nowMs >= state.nextAllowedAtMs;
}

export function smartRankCooldownRemainingSeconds(nowMs: number, state: SmartRankState | null) {
  if (!state) return 0;
  return Math.max(0, Math.ceil((state.nextAllowedAtMs - nowMs) / 1000));
}

export function buildSmartRankState(input: SmartRankInput): SmartRankState {
  const nowMs = input.nowMs ?? Date.now();
  const createdAt = new Date(nowMs).toISOString();
  const targetLimit = normalizeSmartRankTargetLimit(input.targetLimit);
  const targetRows = input.rows.slice(0, targetLimit);
  const rows = targetRows
    .map((row, index) => buildSmartRankRow(row, index + 1))
    .sort((left, right) => {
      if (left.smartScore === right.smartScore) return left.sourceRank - right.sourceRank;
      return right.smartScore - left.smartScore;
    });

  return {
    base: {
      smartRankRunId: input.newId?.() ?? `smart-${nowMs}`,
      createdAt,
      baseSnapshotRunId: input.snapshotRunId,
      timeframe: input.timeframe,
      sortKey: input.rawSortState.sortKey,
      sortDirection: input.rawSortState.direction,
      categoryFilter: input.categoryFilter,
      viewFilter: input.viewFilter,
      targetLimit,
      targetSymbols: targetRows.map((row) => row.symbol)
    },
    rows,
    nextAllowedAtMs: nowMs + SMART_RANK_COOLDOWN_MS
  };
}

export function buildSmartRankRow(row: ScannerRowDTO, sourceRank: number): SmartRankRow {
  const warningCount = row.category === "NO_TRADE" ? (row.riskTagCodes?.length ?? 0) + 1 : (row.riskTagCodes?.length ?? 0);
  const qualityPenalty = dataQualityPenalty(row.dataQuality);
  const attentionScore = Number.isFinite(row.attentionScore) ? row.attentionScore : 0;
  return {
    row,
    sourceRank,
    smartScore: Number((attentionScore - qualityPenalty).toFixed(2)),
    warningCount,
    qualityPenalty
  };
}

function dataQualityPenalty(value: string) {
  if (value === "OK") return 0;
  if (value === "PARTIAL") return 8;
  if (value === "STALE") return 12;
  return 20;
}
