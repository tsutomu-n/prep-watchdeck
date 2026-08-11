const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const midPriceFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 3 });
const fractionalPriceFormatter = new Intl.NumberFormat("en-US", {
  maximumSignificantDigits: 4,
  notation: "standard"
});

export function formatNumber(value: unknown, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未取得";
  return `${numberFormatter.format(value)}${suffix}`;
}

export function formatCompactNumber(value: unknown, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${numberFormatter.format(value)}${suffix}`;
}

export function formatMarketPrice(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return "-";
  if (value >= 1_000) return numberFormatter.format(value);
  if (value >= 1) return midPriceFormatter.format(value);
  return fractionalPriceFormatter.format(value);
}

export function formatUsd(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未取得";
  return `$${numberFormatter.format(value)}`;
}

export function formatRatio(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未取得";
  return numberFormatter.format(value);
}

export function formatDateTime(value: string | number) {
  return new Date(value).toLocaleString("ja-JP");
}
