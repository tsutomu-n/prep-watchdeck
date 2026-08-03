const quoteSuffixes = ["USDGO", "USDT", "USDC", "USD"] as const;

export function formatDisplaySymbol(symbol: string) {
  const normalized = symbol.trim().toUpperCase();
  const suffix = quoteSuffixes.find((candidate) => normalized.endsWith(candidate));
  if (!suffix) return normalized;

  const base = normalized.slice(0, -suffix.length);
  return base || normalized;
}
