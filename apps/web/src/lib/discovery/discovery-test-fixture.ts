import type { DiscoveryResponse, DiscoveryRow, FeatureSnapshotRow, RawFeatureValue } from "$lib/generated/discovery-response";
import { attentionFixture } from "$lib/attention/attention-test-fixture";
import { rankingFixture } from "$lib/market/ranking-test-fixture";

export function discoveryFixture(now = Date.now()): DiscoveryResponse {
  const attention = attentionFixture(now);
  const cutoff = attention.inputs.rankingCutoff;
  const decisionAt = attention.decisionAt;
  const value = (amount: number | null, unit: string, source = "bybit"): RawFeatureValue => ({ value: amount,
    status: amount === null ? "missing" : "ready", reason: amount === null ? "fixture_missing" : null,
    unit, source, startAt: cutoff - 900_000, endAt: cutoff, observedAt: decisionAt, observations: [] });
  const fields = ["referenceClose", "referenceReturn15M", "referenceReturn1H", "referenceReturn24H", "referenceTurnover15M",
    "referenceTurnover1H", "referenceTurnoverRatio15M", "referenceTurnoverRatio1H", "referenceDayRangePosition",
    "nativeReturn15MMedian", "nativeReturn1HMedian", "oiChange15MMedian", "oiChange1HMedian", "fundingAbsMaxPerHour",
    "fundingRangePerHour", "spreadMedianBps", "spreadMaxBps", "markDispersionBps"];
  const rows: DiscoveryRow[] = rankingFixture(undefined, cutoff).rows.map(ranking => {
    const originals = ranking.originals.map(original => ({ instrumentId: original.instrumentId,
      versionId: original.versionId, venue: original.venue, groupId: null, multiplier: 1, current: true }));
    const raw = { ...Object.fromEntries(fields.map(field => [field, value(null, "unavailable")])),
      assetId: ranking.id, asset: ranking.asset, referenceKey: `bybit:${ranking.asset}USDT:fixture-v1`,
      originalInstrumentVersions: originals, decisionAt, identityStatus: "ready", qualityReasons: [],
      referenceClose: value(100, "USDT"), referenceReturn15M: value(3, "%"), referenceTurnover15M: value(100000, "USDT"),
      freshNativeVenueCount: 1, readyNativeVenueCount: 1 } as unknown as FeatureSnapshotRow;
    return { assetId: ranking.id, asset: ranking.asset, referenceKey: raw.referenceKey, originals,
      identityKey: `identity-${ranking.id}`, state: "matched", direction: "up", reason: null, confirmation: "new",
      episodeId: `episode-${ranking.asset}-1`, raw, turnoverComparison: { ...ranking.turnoverComparison,
        previousDayRatio: { status: "ready", value: 3 }, twoDaysAgoRatio: { status: "ready", value: 4 } }, native: [{
          instrumentId: originals[0].instrumentId, versionId: 1, venue: "bitget", sourceSymbol: `${ranking.asset}USDT`,
          quality: "ready", qualityReasons: [], markPrice: value(101, "USDT", "bitget"),
          fundingRateRaw: value(.0001, "rate", "bitget"), fundingRatePerHour: value(.0000125, "rate/hour", "bitget"),
          fundingIntervalSeconds: 28800, openInterestRaw: value(10, "base", "bitget"), openInterestBase: value(10, ranking.asset, "bitget"),
          openInterestNotional: value(1010, "USDT", "bitget"), oiChange: { "15m": value(1, "%", "bitget"), "1h": value(null, "%", "bitget") },
          returnPct: { "15m": value(2, "%", "bitget"), "1h": value(null, "%", "bitget"), "24h": value(null, "%", "bitget") }
        }] };
  });
  return { schemaVersion: "discovery-response-v1", policy: { id: "discovery-reference-turnover-15m-v1",
    turnoverRatioThreshold: 3, returnThresholdPct: 2, windowMinutes: 15, browserSettingsIndependent: true },
    generationId: attention.generationId, decisionAt, rankingCutoff: cutoff, inputs: attention.inputs,
    status: "ready", reason: null, historyAvailableFrom: cutoff - 86400_000 * 7, rows,
    episodes: rows.map(row => ({ id: row.episodeId!, policyId: "discovery-reference-turnover-15m-v1", identityKey: row.identityKey,
      assetId: row.assetId, asset: row.asset, referenceKey: row.referenceKey, originals: row.originals, state: "active",
      startKind: "new", firstObservedAt: decisionAt, lastConfirmedAt: decisionAt, consecutiveConfirmations: 1,
      observedDurationMs: 0, endedAt: null, endReason: null, interruptionReason: null, direction: row.direction,
      firstSourceGenerationId: attention.generationId, lastSourceGenerationId: attention.generationId,
      firstRankingCutoff: cutoff, lastRankingCutoff: cutoff })), nextCursor: null };
}

export function discoverySummaryFixture(now = Date.now()) {
  const response = discoveryFixture(now);
  return { schemaVersion: "discovery-summary-v1" as const, policy: response.policy,
    generationId: response.generationId, decisionAt: response.decisionAt,
    rankingCutoff: response.rankingCutoff, status: response.status, reason: response.reason,
    historyAvailableFrom: response.historyAvailableFrom,
    rows: response.rows.map(({ raw: _raw, native: _native, turnoverComparison: _comparison, ...row }) => row) };
}
