import type { RankedRow, RankingResponse } from "$lib/generated/ranking-response";
import { dailyBaselineAt } from "$lib/market/price-change";
import { rankingQuery } from "$lib/market/ranking";

export function rankingFixture(
  query = rankingQuery("15m", "00:00", "gainers", 0),
  cutoff = Math.floor(Date.now() / 60_000) * 60_000
): RankingResponse {
  const period = query.get("period") as RankingResponse["period"];
  const order = query.get("order") as RankingResponse["order"];
  const reference = query.get("dailyReferenceJst")!;
  const minimum = Number(query.get("minTurnover"));
  const rows: RankedRow[] = [
    { asset: "BTC", change: 2.125, turnover: 500_000 },
    { asset: "ETH", change: 1.2, turnover: 1_500_000 },
    { asset: "SOL", change: -3, turnover: 750_000 },
    { asset: "MISSING", change: null, turnover: null },
    { asset: "NOCHART", change: 0.5, turnover: 100_000 }
  ].map(({ asset, change, turnover }) => ({
    id: `asset:${asset}`, asset, mappingStatus: "verified", venues: ["aster", "bitget", "hyperliquid"],
    originals: [{ venue: "bitget", instrumentId: `bitget:${asset}USDT`, versionId: 1,
      symbol: `${asset}USDT`, baseAsset: asset, multiplier: 1 }],
    reference: { provider: "bybit", symbol: `${asset}USDT`, baseAsset: asset, multiplier: 1,
      quoteAsset: "USDT", settleAsset: "USDT", contractType: "linear_perpetual", revision: "fixture-v1" },
    widget: { status: asset === "NOCHART" ? "unsupported" : "supported",
      symbol: asset === "NOCHART" ? null : `BYBIT:${asset}USDT.P`, reason: asset === "NOCHART" ? "not_listed" : null,
      evidence: asset === "NOCHART" ? [] : ["deterministic fixture only"],
      referenceKey: asset === "NOCHART" ? null : `bybit:${asset}USDT:fixture-v1` },
    state: change === null ? "history_missing" : turnover! < minimum ? "filtered"
      : (order === "gainers" && change <= 0) || (order === "losers" && change >= 0) ? "direction_excluded" : "ready",
    reason: change === null ? "history_missing" : null, returnPct: change, quoteTurnover: turnover, rank: null,
    rankChange: { status: "unavailable", previousRank: null, delta: null, reason: "no_previous_generation" },
    turnoverRatio: { status: period === "daily" || period === "24h" ? "unsupported_period" : change === null ? "history_missing" : "ready",
      value: period === "daily" || period === "24h" || change === null ? null : asset === "BTC" ? 2 : 1 },
    dayRangePosition: { status: change === null ? "history_missing" : "ready", value: change === null ? null : 50 },
    referenceClose: { status: change === null ? "history_missing" : "ready",
      value: change === null ? null : 100 + change },
    windows: {
      "15m": { anchor: cutoff - 15 * 60_000, returnPct: change, quoteTurnover: turnover,
        state: change === null ? "history_missing" : "ready" },
      "1h": { anchor: cutoff - 60 * 60_000, returnPct: change, quoteTurnover: turnover,
        state: change === null ? "history_missing" : "ready" },
      "24h": { anchor: cutoff - 1440 * 60_000, returnPct: change, quoteTurnover: turnover,
        state: change === null ? "history_missing" : "ready" },
      daily: { anchor: dailyBaselineAt(cutoff, reference), returnPct: change, quoteTurnover: turnover,
        state: change === null ? "history_missing" : "ready" }
    },
    turnoverRatios: {
      "15m": { status: change === null ? "history_missing" : "ready",
        value: change === null ? null : asset === "BTC" ? 2 : 1 },
      "1h": { status: change === null ? "history_missing" : "ready",
        value: change === null ? null : asset === "BTC" ? 2 : 1 }
    }
  }));
  const eligible = rows.filter((row) => row.state === "ready");
  eligible.sort((a, b) => order === "turnover" ? b.quoteTurnover! - a.quoteTurnover!
    : order === "losers" ? a.returnPct! - b.returnPct! : b.returnPct! - a.returnPct!);
  eligible.forEach((row, index) => row.rank = index + 1);
  rows.sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity));
  return { schemaVersion: "ranking-v3", metricVersion: "trade-close-quote-turnover-analysis-v3",
    generationId: `fixture:${cutoff}`, mapVersion: "fixture-v1", cutoff, generatedAt: cutoff + 8000,
    previousGenerationId: null, previousCutoff: null,
    rosterGeneratedAt: cutoff, rosterStale: false, stale: false, status: "partial", period,
    dailyReferenceJst: reference, anchor: period === "daily" ? dailyBaselineAt(cutoff, reference)
      : cutoff - (period === "15m" ? 15 : period === "1h" ? 60 : 1440) * 60_000, order, minTurnover: minimum,
    coverage: { sourceInstruments: rows.length, rows: rows.length, cryptoRows: rows.length,
      supported: rows.length, widgetSupported: rows.length - 1, valid: rows.length - 1,
      ranked: eligible.length, reasons: { history_missing: 1 } }, rows };
}
