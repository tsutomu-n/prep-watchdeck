import type { AttentionComponent, AttentionResponse, AttentionRow } from "$lib/generated/attention-response";

export function attentionFixture(now = Date.now()): AttentionResponse {
  const cutoff = Math.floor((now - 12_000) / 60_000) * 60_000;
  const component = (score: number, rank: number, direction: AttentionComponent["direction"] = "unknown"): AttentionComponent => ({
    policyVersion: "fixture-v1", status: "ready", score, rawValue: score / 10, rank,
    rankChange: null, direction, reason: null, inputs: ["referenceReturn15m"], peerCount: 2
  });
  const rows: AttentionRow[] = ["BTC", "ETH"].map((asset, index) => ({
    assetId: `asset:${asset}`, asset, referenceKey: `bybit:${asset}USDT:rev1`,
    originals: [{ instrumentId: `bitget:${asset}USDT`, versionId: 1, venue: "bitget", groupId: asset, multiplier: 1, current: true }],
    components: Object.fromEntries(["confluence", "movement", "activity", "positioning", "dislocation"].map(name =>
      [name, component(90 - index * 20, index + 1, name === "movement" ? (index ? "down" : "up") : "unknown")])),
    readyComponentCount: 4, totalComponentCount: 4, coverageRatio: 1,
    qualityReasons: ["single_native_venue"], dataAsOf: cutoff, identityStatus: "partial"
  }));
  for (const name of ["positioning", "confluence"]) rows[1].components[name] = {
    policyVersion: "fixture-v1", status: "unavailable", score: null, rawValue: null, rank: null,
    rankChange: null, direction: "unknown", reason: name === "confluence" ? "incomplete_components" : "no_ready_inputs", inputs: [], peerCount: 1
  };
  rows[1].readyComponentCount = 3; rows[1].coverageRatio = .75;
  return {
    schemaVersion: "attention-response-v1", generationId: `fixture-${cutoff}`, decisionAt: cutoff + 10_000,
    status: "partial", reason: "partial_components", policyVersion: "fixture-v1",
    inputs: { generationId: `fixture-${cutoff}`, featureVersion: "attention-features-v1", decisionAt: cutoff + 10_000,
      rankingCutoff: cutoff, rankingGeneratedAt: cutoff + 8_000, rankingGenerationId: "ranking-fixture",
      rankingMapVersion: "map-fixture", rankingMetricVersion: "reference-v1", universeGeneratedAt: cutoff,
      serviceGeneratedAt: cutoff, marketMetricsGenerationId: null, marketMetricsGeneratedAt: null,
      marketMetricsCandleCutoff: null, inputSkewSeconds: 8, qualityReasons: ["metrics_unavailable"] },
    coverage: { rows: 2, eligible: 2, confluenceReady: 1, componentReady: { movement: 2, activity: 2, positioning: 1, dislocation: 2 } },
    rows, shadowAllocations: []
  };
}
