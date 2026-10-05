import type { RankedRow, RankingResponse, TurnoverComparison } from "$lib/generated/ranking-response";
import { indicatorLabel, RANKING_MAX_AGE_MS, rankingTimestamp, referenceLabel } from "./ranking";

export const TURNOVER_SURGE_RATIO = 3;
export const PRICE_SURGE_PCT = 2;
export type VolumeSurgeKind = "up" | "down" | "volume";

export function turnoverBarHeights(comparison: TurnoverComparison): number[] | null {
  const samples = [comparison.twoDaysAgo, comparison.previousDay, comparison.current];
  if (samples.some(sample => sample.status !== "ready" || sample.quoteTurnover === null
    || !Number.isFinite(sample.quoteTurnover) || sample.quoteTurnover < 0)) return null;
  const values = samples.map(sample => sample.quoteTurnover!);
  const maximum = Math.max(...values);
  return values.map(value => maximum === 0 ? 0 : value / maximum * 24);
}

export function relativeVolumeState(row: RankedRow, expired = false) {
  const comparison = row.turnoverComparison;
  let reason = expired ? "更新停止・過去時点の値" : "";
  if (!reason && (row.mappingStatus !== "verified"
    || row.state === "reference_invalid" || row.state === "source_unavailable")) {
    reason = "参照契約を利用不可";
  }
  if (!reason) {
    const unavailable = [comparison.current, comparison.previousDay, comparison.twoDaysAgo]
      .find(sample => sample.status !== "ready");
    if (unavailable) reason = indicatorLabel({ status: unavailable.status, value: null }, "倍");
  }
  const ratios = [comparison.previousDayRatio, comparison.twoDaysAgoRatio];
  if (!reason) {
    const unavailable = ratios.find(ratio => ratio.status !== "ready" || ratio.value === null);
    if (unavailable) reason = indicatorLabel(unavailable, "倍");
  }
  const available = !reason && ratios.every(ratio => ratio.value !== null
    && Number.isFinite(ratio.value) && ratio.value >= 0) && turnoverBarHeights(comparison) !== null;
  const strength = available ? Math.min(...ratios.map(ratio => ratio.value!)) : null;
  const change = row.returnPct;
  const direction = expired || change === null || !Number.isFinite(change) ? "unknown"
    : change >= PRICE_SURGE_PCT ? "up" : change <= -PRICE_SURGE_PCT ? "down" : "flat";
  const kind: VolumeSurgeKind | null = strength !== null && strength >= TURNOVER_SURGE_RATIO
    ? direction === "up" || direction === "down" ? direction : "volume" : null;
  return { available, strength, direction, kind, reason: reason || (available ? "" : "入力不整合") };
}

export function relativeVolumeDescription(row: RankedRow, expired = false): string {
  const comparison = row.turnoverComparison;
  const state = relativeVolumeState(row, expired);
  const samples = [
    ["一昨日", comparison.twoDaysAgo], ["昨日", comparison.previousDay], ["現在", comparison.current]
  ] as const;
  const lines = samples.map(([label, sample]) => `${label} ${rankingTimestamp(sample.anchor)}〜${rankingTimestamp(sample.cutoff)} JST: ${
    sample.status === "ready" && sample.quoteTurnover !== null
      ? `${sample.quoteTurnover.toLocaleString("ja-JP", { maximumFractionDigits: 2 })} USDT`
      : indicatorLabel({ value: null, status: sample.status }, "倍")}`);
  return [
    `${row.asset} · ${referenceLabel(row)} · 売買代金の過去日比較`,
    `価格変化 ${row.returnPct === null ? "未取得" : `${row.returnPct > 0 ? "+" : ""}${row.returnPct.toFixed(2)}%`}`,
    ...(state.reason ? [state.reason] : []), ...lines,
    `昨日比 ${indicatorLabel(comparison.previousDayRatio, "倍")} / 一昨日比 ${indicatorLabel(comparison.twoDaysAgoRatio, "倍")}`
  ].join("\n");
}

export function newlyIncreasedRows(
  previous: RankingResponse | null, current: RankingResponse, now: number
): Set<string> {
  if (!previous || previous.stale || current.stale
    || now - previous.cutoff > RANKING_MAX_AGE_MS || now - current.cutoff > RANKING_MAX_AGE_MS
    || current.cutoff !== previous.cutoff + 60_000
    || current.previousGenerationId !== previous.generationId || current.previousCutoff !== previous.cutoff
    || current.mapVersion !== previous.mapVersion || current.metricVersion !== previous.metricVersion
    || current.period !== previous.period || current.order !== previous.order
    || current.minTurnover !== previous.minTurnover || current.dailyReferenceJst !== previous.dailyReferenceJst
    || (current.period === "daily" && current.anchor !== previous.anchor)) return new Set();
  const old = new Map(previous.rows.map(row => [row.id, row]));
  return new Set(current.rows.filter(row => {
    const before = old.get(row.id);
    if (!before) return false;
    const state = relativeVolumeState(before);
    return state.available && state.kind === null && relativeVolumeState(row).kind !== null;
  }).map(row => row.id));
}
