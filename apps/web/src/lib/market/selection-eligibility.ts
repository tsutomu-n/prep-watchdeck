import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";

const usdLikeAssets = new Set(["USD", "USDC", "USDT"]);

export function selectionUnavailableReason(instrument: UniverseInstrumentArtifact): string | null {
  if (!instrument.active) return "取扱いが停止しているため購読できません";
  if (instrument.groupId) return null;
  if (instrument.marketType !== "linear_perpetual" || instrument.executionModel !== "clob") {
    return "この契約の板・約定方式は未対応です";
  }
  if (![instrument.quoteAsset, instrument.settleAsset, instrument.collateralAsset]
    .every(asset => asset != null && usdLikeAssets.has(asset.toUpperCase()))) {
    return "価格表示・決済・担保通貨を確認できないため購読できません";
  }
  if (instrument.quantityUnit !== "base" || instrument.contractMultiplier !== 1) {
    return "Base数量・契約倍率を確認できないため板・約定は購読しません";
  }
  return null;
}
