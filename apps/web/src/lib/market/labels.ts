export function categoryLabel(value: string) {
  const labels: Record<string, string> = {
    ALL: "すべて",
    WATCH: "注視",
    CAUTION: "注意",
    NO_TRADE: "監視除外候補",
    LOW_PRIORITY: "低優先"
  };
  return labels[value] ?? "未分類";
}

export function categoryCompactLabel(value: string) {
  const labels: Record<string, string> = {
    WATCH: "注視",
    CAUTION: "注意",
    NO_TRADE: "除外",
    LOW_PRIORITY: "低優"
  };
  return labels[value] ?? "未分類";
}

export function dataQualityLabel(value: string) {
  const labels: Record<string, string> = {
    OK: "正常",
    STALE: "更新遅延",
    MISSING: "判定不能",
    PARTIAL: "一部データ不足"
  };
  return labels[value] ?? "判定不能";
}

export function abnormalDataQualityLabel(value: string): string | null {
  return value === "OK" ? null : dataQualityLabel(value);
}

export function activityPhaseLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    BURST: "急増",
    EXPANDING: "拡大",
    SUSTAINED: "持続",
    COOLING: "失速",
    NORMAL: "平常",
    UNKNOWN: "判定不能"
  };
  return value ? (labels[value] ?? "判定不能") : "判定不能";
}

export function activityPhaseWatchlistLabel(
  value: string | null | undefined,
  dataQuality?: string
): string | null {
  if (value === "UNKNOWN" && dataQuality && dataQuality !== "OK") return null;
  return value === "NORMAL" ? null : activityPhaseLabel(value);
}

export function snapshotStatusLabel(value: string) {
  const labels: Record<string, string> = {
    OK: "正常",
    STALE: "古い",
    PARTIAL: "一部不足",
    ERROR: "エラー"
  };
  return labels[value] ?? "未分類";
}

export function dataSourceLabel(value: string) {
  const labels: Record<string, string> = {
    live: "ライブ",
    cache: "キャッシュ",
    fixture: "検証データ"
  };
  return labels[value] ?? "未分類";
}

export function templateLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    aggressive: "積極",
    balanced: "標準",
    conservative: "慎重",
    basic: "基本",
    stale: "古いデータ",
    "thin-spike": "薄商い急変"
  };
  return value ? (labels[value] ?? "未分類") : "";
}

export function codeLabel(value: string, fallback = value) {
  const labels: Record<string, string> = {
    VOLUME_CONFIRMED_UP: "出来高確認済み上昇",
    VOLUME_CONFIRMED_DOWN: "出来高確認済み下落",
    VOLUME_CONFIRMED: "出来高確認済み",
    VOLUME_LEADING: "出来高先行",
    VOLUME_SPIKE: "出来高急増",
    LOW_REACTION: "反応弱め",
    PRICE_LEADING_WEAK_VOLUME: "価格先行・出来高弱め",
    STALE_DATA: "古いデータ",
    PARTIAL_DATA: "一部不足",
    THIN_SPIKE: "薄商い急変",
    THIN_TURNOVER: "売買代金不足",
    SINGLE_BAR_CONCENTRATION: "単発集中",
    TOO_ROUGH: "荒すぎる足",
    FUNDING_OVERHEATED: "資金調達過熱",
    DATA_NOT_OK: "データ注意",
    DATA_COVERAGE_LOW: "データ不足",
    DATA_STALE: "古いデータ",
    DATA_PARTIAL: "一部不足",
    DATA_MISSING: "データ欠損",
    DATA_GAP_REPAIRABLE: "Bitget補修対象",
    DATA_HISTORY_SHORT: "履歴不足",
    DATA_ZERO_VOLUME: "ゼロ出来高注意",
    BTC_LINKED: "BTC連動",
    BTC_RELATIVE_STRONG: "BTC比で強い",
    DOWN_SURGE: "急落",
    MISSING: "欠損",
    NONE: "なし"
  };
  return labels[value] ?? fallback;
}

export function changeTone(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "neutral";
  if (value > 0) return "good";
  if (value < 0) return "risk";
  return "neutral";
}

export function dataQualityClass(value: string) {
  return value === "OK" ? "good" : "risk";
}

export function rowQualityClass(row: { category: string; dataQuality: string }) {
  return row.category === "NO_TRADE" || row.dataQuality !== "OK" ? "risk" : "ok";
}

export function rowExclusionLabels(row: {
  category: string;
  label: string;
  dataQuality: string;
  riskTagCodes?: string[] | null;
}) {
  const labels = [
    row.category === "NO_TRADE" ? "監視除外候補" : null,
    row.category === "NO_TRADE" ? codeLabel(row.label) : null,
    row.dataQuality !== "OK" ? dataQualityLabel(row.dataQuality) : null,
    ...(row.riskTagCodes ?? []).map((code) => codeLabel(code))
  ].filter((value): value is string => Boolean(value));
  return [...new Set(labels)];
}

export function openInterestStateLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    INCREASING: "増加",
    RISING: "増加",
    STABLE: "横ばい",
    DECREASING: "減少",
    FALLING: "減少"
  };
  return value ? (labels[value] ?? "不明") : "不明";
}
