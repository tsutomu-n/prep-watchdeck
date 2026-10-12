import type { ActivityWindow, NativeActivityArtifact, NativeActivityRow } from "$lib/generated/native-activity";

export function nativeActivityFixture(now = Date.now()): NativeActivityArtifact {
  const cutoff = Math.floor(now / 60_000) * 60_000 - 180_000;
  const stamp = (time: number) => new Date(time).toISOString();
  const ready = (value: number) => ({ value, status: "ready" as const });
  const makeWindow = (minutes: 15 | 60): ActivityWindow => {
    const history = [50_000, 100_000, 300_000, 240_000].map((turnover, index) => ({
      startAt: stamp(cutoff - (4 - index) * minutes * 60_000),
      endAt: stamp(cutoff - (3 - index) * minutes * 60_000),
      turnover: ready(turnover), priceChangePct: ready(index === 3 ? -2.5 : 1)
    })) as ActivityWindow["history"];
    return { minutes, current: history[3], history,
      baselineTurnover: ready(80_000), baselineDays: 7,
      baselineEndTimes: Array.from({ length: 7 }, (_, day) => stamp(cutoff - (7 - day) * 86_400_000)),
      relativeRatio: ready(3), previousChangePct: ready(-20) };
  };
  const row: NativeActivityRow = { venue: "bitget", venueInstrumentId: "bitget:BTCUSDT",
    venueInstrumentVersionId: 1, sourceSymbol: "BTCUSDT", quoteAsset: "USDT",
    windows: { "15m": makeWindow(15), "1h": makeWindow(60) } };
  return { schemaVersion: 1, metricVersion: "bitget-activity-v1", generationId: "isolated",
    generatedAt: stamp(now), candleCutoff: stamp(cutoff), rows: [row] };
}
