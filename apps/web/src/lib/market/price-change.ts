export const DEFAULT_REFERENCE_TIME = "00:00";
export const REFERENCE_TIME_STORAGE_KEY = "prep-watchdeck:daily-change-reference";
export const PRICE_CHANGE_REFRESH_MS = 60_000;
export const PRICE_CHANGE_MAX_AGE_MS = 120_000;

const DAY_MS = 86_400_000;
const JST_OFFSET_MS = 9 * 60 * 60 * 1_000;

export type PriceChangeUnavailableReason =
  | "baseline_missing"
  | "latest_missing"
  | "latest_stale";

export interface DailyPriceChange {
  venueInstrumentId: string;
  venueInstrumentVersionId: number;
  referenceTime: string;
  baselineAt: string;
  generatedAt: string;
  status: "ready" | "unavailable";
  reason: PriceChangeUnavailableReason | null;
  baselinePrice: number | null;
  currentPrice: number | null;
  currentCandleAt: string | null;
  changePercent: number | null;
}

export function isReferenceTime(value: unknown): value is string {
  return typeof value === "string" && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value);
}

/** The most recent occurrence of the user's daily reference time, always in JST. */
export function dailyBaselineAt(nowMs: number, referenceTime: string): number {
  if (!Number.isFinite(nowMs) || !isReferenceTime(referenceTime)) {
    throw new RangeError("Invalid daily reference time");
  }
  const [hours, minutes] = referenceTime.split(":").map(Number);
  const dayStart = Math.floor((nowMs + JST_OFFSET_MS) / DAY_MS) * DAY_MS - JST_OFFSET_MS;
  const candidate = dayStart + (hours * 60 + minutes) * 60_000;
  return candidate <= nowMs ? candidate : candidate - DAY_MS;
}

export function calculatePriceChange(current: number, baseline: number): number | null {
  if (!Number.isFinite(current) || !Number.isFinite(baseline) || current <= 0 || baseline <= 0) {
    return null;
  }
  const change = (current / baseline - 1) * 100;
  return Number.isFinite(change) ? change : null;
}

export function formatPriceChange(value: number): string {
  return `${new Intl.NumberFormat("ja-JP", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: "exceptZero"
  }).format(value)}%`;
}

export function priceChangeUnavailableLabel(reason: PriceChangeUnavailableReason): string {
  switch (reason) {
    case "baseline_missing": return "基準足なし";
    case "latest_missing": return "約定足なし";
    case "latest_stale": return "約定足が古い";
  }
}

export function readStoredReferenceTime(storage: Pick<Storage, "getItem">): string {
  try {
    const value = storage.getItem(REFERENCE_TIME_STORAGE_KEY);
    return isReferenceTime(value) ? value : DEFAULT_REFERENCE_TIME;
  } catch {
    return DEFAULT_REFERENCE_TIME;
  }
}

export function writeStoredReferenceTime(
  storage: Pick<Storage, "setItem">,
  referenceTime: string
): boolean {
  if (!isReferenceTime(referenceTime)) return false;
  try {
    storage.setItem(REFERENCE_TIME_STORAGE_KEY, referenceTime);
    return true;
  } catch {
    return false;
  }
}
