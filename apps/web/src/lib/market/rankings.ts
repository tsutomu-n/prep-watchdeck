export type RankingValue = { symbol: string; value: number };
export type RankingMetaValue = {
  limit?: number;
  totalEligible?: number;
  excludedNoTrade?: boolean;
};
export type RankingTree = {
  timeframes?: Record<string, Record<string, RankingValue[]>>;
  meta?: { timeframes?: Record<string, Record<string, RankingMetaValue>> };
};
export type RankingPositionResult = {
  rank: number | null;
  value: number | null;
  limit: number;
  totalEligible: number;
};

export function rankingPosition(rankings: unknown, timeframe: string, metric: string, symbol: string) {
  const tree = rankings as RankingTree | undefined;
  const items = tree?.timeframes?.[timeframe]?.[metric];
  if (!items) return null;
  const meta = tree?.meta?.timeframes?.[timeframe]?.[metric];
  const limit = meta?.limit ?? items.length;
  const totalEligible = meta?.totalEligible ?? items.length;
  const index = items.findIndex((item) => item.symbol === symbol);
  if (index < 0) return { rank: null, value: null, limit, totalEligible };
  return { rank: index + 1, value: items[index].value, limit, totalEligible };
}
