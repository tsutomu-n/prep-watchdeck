export type VolumeRatio15mMeta = {
  windowMinutes: number;
  sampleStepMinutes: number;
  baselineSampleCount: number;
  approxBaselineSpanMinutes: number;
  statistic: "median";
  floorUsdt: number;
};

const BASELINE_FALLBACK = "基準期間を取得できません";
const HELP_FALLBACK =
  "現在15分のUSDT売買代金をrolling 15分売買代金の基準中央値と比較します。基準期間の詳細は取得できません。";
const integerFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isPositiveFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

export function parseVolumeRatio15mMeta(value: unknown): VolumeRatio15mMeta | null {
  if (
    !isRecord(value) ||
    value.windowMinutes !== 15 ||
    value.sampleStepMinutes !== 5 ||
    !isPositiveSafeInteger(value.baselineSampleCount) ||
    !isPositiveSafeInteger(value.approxBaselineSpanMinutes) ||
    value.approxBaselineSpanMinutes !== value.baselineSampleCount * value.sampleStepMinutes ||
    value.statistic !== "median" ||
    !isPositiveFinite(value.floorUsdt)
  ) {
    return null;
  }

  return {
    windowMinutes: value.windowMinutes,
    sampleStepMinutes: value.sampleStepMinutes,
    baselineSampleCount: value.baselineSampleCount,
    approxBaselineSpanMinutes: value.approxBaselineSpanMinutes,
    statistic: value.statistic,
    floorUsdt: value.floorUsdt
  };
}

function formatApproxSpan(minutes: number) {
  if (minutes % 60 === 0) return `約${minutes / 60}h`;
  return `約${minutes}分`;
}

export function formatVolumeRatioBaseline(value: unknown) {
  const meta = parseVolumeRatio15mMeta(value);
  if (!meta) return BASELINE_FALLBACK;
  return `直近${formatApproxSpan(meta.approxBaselineSpanMinutes)}中央値比`;
}

export function formatVolumeRatioHelp(value: unknown) {
  const meta = parseVolumeRatio15mMeta(value);
  if (!meta) return HELP_FALLBACK;
  const span = formatApproxSpan(meta.approxBaselineSpanMinutes);
  return `現在15分のUSDT売買代金 ÷ 過去${meta.baselineSampleCount}サンプル（${meta.sampleStepMinutes}分刻み、${span}）のrolling 15分売買代金中央値（基準下限 ${integerFormatter.format(meta.floorUsdt)} USDT）`;
}
