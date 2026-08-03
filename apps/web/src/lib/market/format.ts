const numberFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

export function formatNumber(value: unknown, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未取得";
  return `${numberFormatter.format(value)}${suffix}`;
}

export function formatCompactNumber(value: unknown, suffix = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return `${numberFormatter.format(value)}${suffix}`;
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
