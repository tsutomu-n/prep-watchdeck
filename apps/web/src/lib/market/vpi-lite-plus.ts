export type VpiLitePlusState =
  | "CALM"
  | "EARLY_ACTIVITY"
  | "ACTIVE_MOVE"
  | "THIN_VOLATILITY"
  | "SINGLE_BAR_SUSPECT"
  | "DATA_INSUFFICIENT"
  | "DATA_STALE"
  | "UNKNOWN";

export type VpiLitePlusFundingState = "UNKNOWN" | "NORMAL" | "OVERHEATED";
export type VpiLitePlusOpenInterestState = "UNKNOWN" | "AVAILABLE";
export type VpiLitePlusDataQuality = "OK" | "INSUFFICIENT" | "STALE" | "ERROR";

export type VpiLitePlusItem = {
  symbol: string;
  state: VpiLitePlusState;
  score: number;
  reasonCodes: string[];
  riskTagCodes: string[];
  fundingState: VpiLitePlusFundingState;
  openInterestState: VpiLitePlusOpenInterestState;
  dataQuality: VpiLitePlusDataQuality;
  dataAsOf: number | null;
};

export type VpiLitePlusSummary = {
  schemaVersion: 1;
  mode: "lite_plus_v0";
  generatedAt: number;
  benchmarks: VpiLitePlusItem[];
  targets: VpiLitePlusItem[];
};

const states = new Set<VpiLitePlusState>([
  "CALM",
  "EARLY_ACTIVITY",
  "ACTIVE_MOVE",
  "THIN_VOLATILITY",
  "SINGLE_BAR_SUSPECT",
  "DATA_INSUFFICIENT",
  "DATA_STALE",
  "UNKNOWN"
]);
const fundingStates = new Set<VpiLitePlusFundingState>(["UNKNOWN", "NORMAL", "OVERHEATED"]);
const openInterestStates = new Set<VpiLitePlusOpenInterestState>(["UNKNOWN", "AVAILABLE"]);
const dataQualities = new Set<VpiLitePlusDataQuality>(["OK", "INSUFFICIENT", "STALE", "ERROR"]);

export function parseVpiLitePlusSummary(value: unknown): VpiLitePlusSummary | null {
  if (
    !isRecord(value) ||
    value.schemaVersion !== 1 ||
    value.mode !== "lite_plus_v0" ||
    !isNonNegativeSafeInteger(value.generatedAt) ||
    !Array.isArray(value.benchmarks) ||
    !Array.isArray(value.targets)
  ) {
    return null;
  }
  return {
    schemaVersion: 1,
    mode: "lite_plus_v0",
    generatedAt: value.generatedAt,
    benchmarks: value.benchmarks.flatMap((item) => {
      const parsed = parseVpiLitePlusItem(item);
      return parsed ? [parsed] : [];
    }),
    targets: value.targets.flatMap((item) => {
      const parsed = parseVpiLitePlusItem(item);
      return parsed ? [parsed] : [];
    })
  };
}

export function parseVpiLitePlusItem(value: unknown): VpiLitePlusItem | null {
  if (
    !isRecord(value) ||
    typeof value.symbol !== "string" ||
    !/^[A-Z0-9_-]+$/.test(value.symbol) ||
    !isEnumValue(states, value.state) ||
    typeof value.score !== "number" ||
    !Number.isFinite(value.score) ||
    value.score < 0 ||
    value.score > 100 ||
    !isStringArray(value.reasonCodes) ||
    !isStringArray(value.riskTagCodes) ||
    !isEnumValue(fundingStates, value.fundingState) ||
    !isEnumValue(openInterestStates, value.openInterestState) ||
    !isEnumValue(dataQualities, value.dataQuality) ||
    !(value.dataAsOf === null || isNonNegativeSafeInteger(value.dataAsOf))
  ) {
    return null;
  }
  return {
    symbol: value.symbol,
    state: value.state,
    score: value.score,
    reasonCodes: [...value.reasonCodes],
    riskTagCodes: [...value.riskTagCodes],
    fundingState: value.fundingState,
    openInterestState: value.openInterestState,
    dataQuality: value.dataQuality,
    dataAsOf: value.dataAsOf
  };
}

export function resolveVpiLitePlusRowItem(
  summary: VpiLitePlusSummary,
  selectedSymbol: string,
  value: unknown
): VpiLitePlusItem | null {
  const rowItem = parseVpiLitePlusItem(value);
  if (!rowItem || rowItem.symbol !== selectedSymbol) return null;
  const canonical = [...summary.benchmarks, ...summary.targets].find(
    (item) => item.symbol === selectedSymbol
  );
  return canonical && sameItem(canonical, rowItem) ? rowItem : null;
}

export function vpiStateLabel(state: VpiLitePlusState): string {
  return {
    CALM: "平常",
    EARLY_ACTIVITY: "活動増加",
    ACTIVE_MOVE: "活発な変動",
    THIN_VOLATILITY: "薄商いの変動",
    SINGLE_BAR_SUSPECT: "単発足への偏り",
    DATA_INSUFFICIENT: "データ不足",
    DATA_STALE: "データ遅延",
    UNKNOWN: "判定不能"
  }[state];
}

export function vpiReasonLabel(code: string): string {
  return (
    {
      ABS_RETURN_UP: "値動きの活動増加",
      TURNOVER_UP: "売買代金の活動増加",
      RANGE_UP: "値幅の活動増加"
    }[code] ?? code
  );
}

export function vpiRiskLabel(code: string): string {
  return (
    {
      THIN_TURNOVER: "売買代金が薄い",
      SINGLE_BAR_SUSPECT: "変動が1本へ偏っている",
      FUNDING_OVERHEATED: "Fundingが高偏り",
      COMPUTE_ERROR: "計算できない"
    }[code] ?? code
  );
}

export function vpiDataQualityLabel(quality: VpiLitePlusDataQuality): string {
  return {
    OK: "確認済み",
    INSUFFICIENT: "データ不足",
    STALE: "データ遅延",
    ERROR: "判定不能"
  }[quality];
}

export function vpiFundingStateLabel(state: VpiLitePlusFundingState): string {
  return { UNKNOWN: "未取得", NORMAL: "通常範囲", OVERHEATED: "高偏り" }[state];
}

export function vpiOpenInterestStateLabel(state: VpiLitePlusOpenInterestState): string {
  return { UNKNOWN: "未取得", AVAILABLE: "取得あり" }[state];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isEnumValue<T extends string>(values: Set<T>, value: unknown): value is T {
  return typeof value === "string" && values.has(value as T);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string" && item.length > 0);
}

function isNonNegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function sameItem(left: VpiLitePlusItem, right: VpiLitePlusItem): boolean {
  return (
    left.symbol === right.symbol &&
    left.state === right.state &&
    left.score === right.score &&
    arraysEqual(left.reasonCodes, right.reasonCodes) &&
    arraysEqual(left.riskTagCodes, right.riskTagCodes) &&
    left.fundingState === right.fundingState &&
    left.openInterestState === right.openInterestState &&
    left.dataQuality === right.dataQuality &&
    left.dataAsOf === right.dataAsOf
  );
}

function arraysEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
