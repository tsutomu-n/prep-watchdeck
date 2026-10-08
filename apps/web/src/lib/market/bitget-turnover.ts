import type { RankedRow } from "$lib/generated/ranking-response";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { formatTurnover } from "./turnover-format";

type Snapshot = Pick<UniverseSnapshotArtifact, "generatedAt" | "items">;
type Turnover = { value: number | null; observedAt: string | null; reason: string | null };
const MAX_AGE_MS = 120_000;

function fresh(timestamp: string | null, now: number): boolean {
  const age = timestamp === null ? NaN : now - Date.parse(timestamp);
  return Number.isFinite(age) && age >= -1000 && age <= MAX_AGE_MS;
}

/** Native quote turnover belongs to one exact original contract, never a reference or alias. */
export function bitgetTurnover(row: RankedRow, snapshot: Snapshot | null, now: number): Turnover {
  const missing = (reason: string): Turnover => ({ value: null, observedAt: null, reason });
  if (!snapshot) return missing("Bitgetのデータを取得できません");
  if (!fresh(snapshot.generatedAt, now)) return missing("Bitgetのデータが期限切れです");
  const originals = row.originals.filter(original => original.venue === "bitget");
  if (originals.length !== 1) return missing("Bitgetの対象契約を特定できません");
  const original = originals[0];
  const matches = snapshot.items.filter(item => item.venue === "bitget"
    && item.venueInstrumentId === original.instrumentId);
  if (matches.length !== 1) return missing("Bitgetの対象契約を取得できません");
  const item = matches[0];
  if (!item.active || item.marketType !== "linear_perpetual"
    || item.venueInstrumentVersionId !== original.versionId || item.sourceSymbol !== original.symbol)
    return missing("Bitgetの契約情報の確認待ちです");
  if (!fresh(item.observedAt, now) || !fresh(item.sourceAt, now) || !fresh(item.cycleAt, now))
    return missing("Bitgetのデータが期限切れまたは時刻未確認です");
  if (item.quality !== "ready") return missing("Bitgetのデータに品質警告があります");
  if (item.quoteAsset !== "USDT" || item.volume24hUnit !== "quote")
    return missing("Bitgetの売買代金の単位を確認できません");
  if (item.volume24hRaw === null || !Number.isFinite(item.volume24hRaw) || item.volume24hRaw < 0)
    return missing("Bitgetの24時間売買代金は未取得です");
  return { value: item.volume24hRaw, observedAt: item.observedAt, reason: null };
}

export function formatBitgetTurnover(value: number | null, decimals: number): string {
  if (value === null || !Number.isFinite(value) || value < 0) return "—";
  if (value >= 1_000_000) return `${formatTurnover(value / 1_000_000, decimals)}m`;
  if (value >= 1_000) return `${formatTurnover(value / 1_000, decimals)}k`;
  return formatTurnover(value, decimals);
}
