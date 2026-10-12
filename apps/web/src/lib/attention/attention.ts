import type { AttentionResponse, AttentionRow, OriginalReference } from "$lib/generated/attention-response";
import type { FavoriteTarget } from "$lib/server/user-workspace-repository";

export const COMPONENTS = ["movement", "activity", "positioning", "dislocation"] as const;
export type ComponentName = typeof COMPONENTS[number] | "confluence";
export const COMPONENT_LABELS: Record<ComponentName, string> = {
  confluence: "総合注目", movement: "値動き", activity: "取引活性", positioning: "建玉・資金調達", dislocation: "価格の乖離"
};
const REASONS: Record<string, string> = {
  incomplete_components: "4成分が揃っていません", insufficient_peers: "比較対象が不足しています",
  no_ready_inputs: "計算できる入力がありません", insufficient_native_venues: "取引所の観測数が不足しています",
  single_native_venue: "取引所の観測は1か所です", original_missing: "元の契約が一部見つかりません",
  original_version_mismatch: "契約の版が一致しません", no_current_original: "現在の契約が見つかりません",
  reference_missing: "参照銘柄がありません", identity_ineligible: "銘柄の対応を確認できません",
  metrics_unavailable: "取引所の指標を取得できません", partial_components: "一部の成分は未算出です",
  ranking_unavailable: "参照データの取得を待っています", attention_stale: "更新が遅れています",
  source_stale: "入力データが古くなっています", market_input_unavailable: "市場データの取得を待っています",
  storage_unavailable: "新しい世代を保存できません", awaiting_input_validation: "入力を確認しています"
};

export function reasonLabel(reason: string | null) { return reason ? REASONS[reason] ?? reason : "—"; }
export function displayScore(score: number | null) { return score === null ? "—" : score.toFixed(1); }
export function referenceLink(row: AttentionRow) {
  return row.referenceKey ? `/?mode=reference&selected=${encodeURIComponent(row.assetId)}` : null;
}
export function nativeLink(original: OriginalReference) {
  return original.current ? `/?mode=native&instrument=${encodeURIComponent(original.instrumentId)}&version=${original.versionId}` : null;
}
export function matchingFavorites(row: AttentionRow, favorites: FavoriteTarget[]) {
  const originals = row.originals.map(original => `${original.instrumentId}:${original.versionId}`).sort();
  return favorites.filter(target => target.kind === "instrument"
    ? row.originals.some(original => original.current && original.instrumentId === target.id && original.versionId === target.version)
    : target.id === row.assetId && target.referenceKey === row.referenceKey &&
      JSON.stringify([...target.originals].sort()) === JSON.stringify(originals));
}
export function isFavorite(row: AttentionRow, favorites: FavoriteTarget[]) { return matchingFavorites(row, favorites).length > 0; }
export function visibleRows(response: AttentionResponse, component: ComponentName, query: string,
  readyOnly: boolean, prioritizeFavorites: boolean, favorites: Set<string>) {
  const normalized = query.trim().toLocaleLowerCase();
  return response.rows.filter(row => (!readyOnly || row.components[component].status === "ready") &&
    (!normalized || `${row.asset} ${row.assetId}`.toLocaleLowerCase().includes(normalized)))
    .sort((a, b) => (prioritizeFavorites ? Number(favorites.has(b.assetId)) - Number(favorites.has(a.assetId)) : 0) ||
      (a.components[component].rank ?? Infinity) - (b.components[component].rank ?? Infinity) || a.assetId.localeCompare(b.assetId));
}
