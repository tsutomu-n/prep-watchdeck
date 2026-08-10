const FALLBACK = "74h候補条件の詳細を取得できません。snapshot更新後に再確認してください。";
const TURNOVER_MODE = "current_24h_vs_74h_ago_24h";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonNegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

export function formatCandidateRule74h(value: unknown) {
  if (
    !isRecord(value) ||
    value.operator !== "AND" ||
    value.turnoverMode !== TURNOVER_MODE ||
    !isNonNegativeFinite(value.priceAbsPct) ||
    !isNonNegativeFinite(value.turnoverIncreasePct) ||
    !isNonNegativeSafeInteger(value.eligible) ||
    !isNonNegativeSafeInteger(value.notMatched) ||
    !isNonNegativeSafeInteger(value.unknown)
  ) {
    return FALLBACK;
  }

  return `74h条件: 価格±${value.priceAbsPct}%以上 かつ 24h売買代金+${value.turnoverIncreasePct}%以上（合致${value.eligible} / 未一致${value.notMatched} / 判定不能${value.unknown}）`;
}
