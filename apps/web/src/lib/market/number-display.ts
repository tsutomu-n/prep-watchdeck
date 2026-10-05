/** Display rounding only. Prices keep their own precision-preserving formatter. */
export function displayNumber(value: number | null | undefined, digits: number, compact = false, signed = false): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const precision = Number.isInteger(digits) && digits >= 0 && digits <= 6 ? digits : 2;
  if (value !== 0 && Math.abs(value) < 0.5 * 10 ** -precision) {
    const minimum = (10 ** -precision).toLocaleString("en-US", { maximumFractionDigits: precision });
    return value < 0 ? `>−${minimum}` : `${signed ? "+" : ""}<${minimum}`;
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: precision, notation: compact ? "compact" : "standard",
    signDisplay: signed ? "exceptZero" : "auto"
  }).format(value);
}
