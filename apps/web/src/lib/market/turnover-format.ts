export const DEFAULT_TURNOVER_DECIMALS = 2;

export function isTurnoverDecimals(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 4;
}

const formats = Array.from({ length: 5 }, (_, maximumFractionDigits) => ({
  standard: new Intl.NumberFormat("en-US", { maximumFractionDigits }),
  compact: new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits })
}));

/** Presentation only: never use this string for ordering, filtering or calculations. */
export function formatTurnover(
  value: number | null | undefined, decimals = DEFAULT_TURNOVER_DECIMALS, compact = false
): string {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  const digits = isTurnoverDecimals(decimals) ? decimals : DEFAULT_TURNOVER_DECIMALS;
  const formatter = compact && value >= 10_000 ? formats[digits].compact : formats[digits].standard;
  const formatted = formatter.format(value);
  return value > 0 && formatted === "0"
    ? `<${formats[digits].standard.format(10 ** -digits)}` : formatted;
}
