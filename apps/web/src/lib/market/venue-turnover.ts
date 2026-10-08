import type { RankedRow } from "$lib/generated/ranking-response";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { formatTurnover } from "./turnover-format";

type Snapshot = Pick<UniverseSnapshotArtifact, "generatedAt" | "items">;
type Turnover = { unit: "USDT" | "USDC" | null; value: number | null; observedAt: string | null; reason: string | null };
const MAX_AGE_MS = 120_000;

function fresh(timestamp: string | null, now: number): boolean {
  const age = timestamp === null ? NaN : now - Date.parse(timestamp);
  return Number.isFinite(age) && age >= -1000 && age <= MAX_AGE_MS;
}

/** Native quote turnover belongs to one exact original contract, never a reference or alias. */
export function venueTurnover(
  venue: "bitget" | "hyperliquid", row: RankedRow, snapshot: Snapshot | null, now: number
): Turnover {
  const label = venue === "bitget" ? "Bitget" : "Hyperliquid";
  const missing = (reason: string): Turnover => ({ value: null, unit: null, observedAt: null, reason });
  if (!snapshot) return missing(`${label}のデータを取得できません`);
  if (!fresh(snapshot.generatedAt, now)) return missing(`${label}のデータが期限切れです`);
  const originals = row.originals.filter(original => original.venue === venue);
  if (originals.length !== 1) return missing(`${label}の対象契約を特定できません`);
  const original = originals[0];
  const matches = snapshot.items.filter(item => item.venue === venue
    && item.venueInstrumentId === original.instrumentId);
  if (matches.length !== 1) return missing(`${label}の対象契約を取得できません`);
  const item = matches[0];
  if (!item.active || item.marketType !== "linear_perpetual"
    || item.venueInstrumentVersionId !== original.versionId || item.sourceSymbol !== original.symbol)
    return missing(`${label}の契約情報の確認待ちです`);
  // Hyperliquid metaAndAssetCtxs has no source timestamp; retain the collector's observation time.
  const sourceFresh = venue === "hyperliquid" && item.sourceAt === null || fresh(item.sourceAt, now);
  if (!fresh(item.observedAt, now) || !sourceFresh || !fresh(item.cycleAt, now))
    return missing(`${label}のデータが期限切れまたは時刻未確認です`);
  if (item.quality !== "ready") return missing(`${label}のデータに品質警告があります`);
  if ((item.quoteAsset !== "USDT" && !(venue === "hyperliquid" && item.quoteAsset === "USDC"))
    || item.volume24hUnit !== "quote")
    return missing(`${label}の売買代金の単位を確認できません`);
  if (item.volume24hRaw === null || !Number.isFinite(item.volume24hRaw) || item.volume24hRaw < 0)
    return missing(`${label}の24時間売買代金は未取得です`);
  return { value: item.volume24hRaw, unit: item.quoteAsset, observedAt: item.observedAt, reason: null };
}

export function formatVenueTurnover(value: number | null, decimals: number): string {
  if (value === null || !Number.isFinite(value) || value < 0) return "—";
  if (value >= 1_000_000) return `${formatTurnover(value / 1_000_000, decimals)}m`;
  if (value >= 1_000) return `${formatTurnover(value / 1_000, decimals)}k`;
  return formatTurnover(value, decimals);
}
