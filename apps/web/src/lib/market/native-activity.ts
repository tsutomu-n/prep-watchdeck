import type { NativeActivityArtifact, NativeActivityRow } from "$lib/generated/native-activity";
import type { RankedRow } from "$lib/generated/ranking-response";

type ActivityResult = { row: NativeActivityRow | null; reason: string | null };

export function nativeActivity(
  row: RankedRow, artifact: NativeActivityArtifact | null, now: number
): ActivityResult {
  const unavailable = (reason: string): ActivityResult => ({ row: null, reason });
  if (!artifact) return unavailable("Bitgetの短時間データを取得できません");
  const generatedAge = now - Date.parse(artifact.generatedAt);
  const cutoffAge = now - Date.parse(artifact.candleCutoff);
  if (!Number.isFinite(generatedAge) || !Number.isFinite(cutoffAge)
    || generatedAge < -1000 || generatedAge > 120_000 || cutoffAge < 0 || cutoffAge > 300_000)
    return unavailable("Bitgetの短時間データが期限切れまたは時刻未確認です");
  const originals = row.originals.filter(original => original.venue === "bitget");
  if (originals.length !== 1) return unavailable("Bitgetの対象契約を特定できません");
  const original = originals[0];
  const matches = artifact.rows.filter(item => item.venue === "bitget"
    && item.venueInstrumentId === original.instrumentId);
  if (matches.length !== 1) return unavailable("Bitgetの対象契約の短時間データがありません");
  const item = matches[0];
  if (item.venueInstrumentVersionId !== original.versionId || item.sourceSymbol !== original.symbol
    || item.quoteAsset !== "USDT") return unavailable("Bitgetの契約情報の確認待ちです");
  return { row: item, reason: null };
}

export function nativeActivityKind(
  item: NativeActivityRow | null, thresholds: { surgeRatio: number; directionPct: number }
): "up" | "down" | "volume" | null {
  const window = item?.windows["15m"];
  if (!window || window.relativeRatio.status !== "ready" || window.relativeRatio.value === null
    || window.relativeRatio.value < thresholds.surgeRatio) return null;
  const price = window.current.priceChangePct;
  if (price.status === "ready" && price.value !== null) {
    if (price.value >= thresholds.directionPct) return "up";
    if (price.value <= -thresholds.directionPct) return "down";
  }
  return "volume";
}
