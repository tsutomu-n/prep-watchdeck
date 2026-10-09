import Ajv from "ajv";
import schema from "../../../../../schemas/discovery-response.schema.json";
import type { DiscoveryResponse, DiscoveryRow, RawFeatureValue } from "$lib/generated/discovery-response";
import type { ComparisonPin, FavoriteTarget } from "$lib/server/user-workspace-repository";

const validate = new Ajv({ allErrors: false, strict: false, strictNumbers: true }).compile<DiscoveryResponse>(schema);
export function parseDiscovery(value: unknown, now = Date.now()): DiscoveryResponse {
  if (!validate(value)) throw new Error("候補データの形式が不正です");
  if ((value.decisionAt !== null && value.decisionAt > now + 1000) ||
      new Set(value.rows.map(row => row.assetId)).size !== value.rows.length ||
      (value.inputs !== null && (value.inputs.decisionAt !== value.decisionAt ||
        value.inputs.generationId !== value.generationId || value.inputs.rankingCutoff !== value.rankingCutoff)) ||
      new Set(value.episodes.map(episode => episode.id)).size !== value.episodes.length ||
      value.rows.some(row => row.raw.assetId !== row.assetId || row.raw.referenceKey !== row.referenceKey ||
        JSON.stringify(row.raw.originalInstrumentVersions) !== JSON.stringify(row.originals) ||
        new Set(row.originals.map(item => `${item.instrumentId}:${item.versionId}`)).size !== row.originals.length ||
        new Set(row.native.map(item => `${item.instrumentId}:${item.versionId}`)).size !== row.native.length ||
        row.native.some(native => !row.originals.some(original => original.instrumentId === native.instrumentId &&
          original.versionId === native.versionId && original.venue === native.venue)) ||
        row.raw.decisionAt !== value.decisionAt || Object.values(row.raw).some(feature => {
          if (!feature || typeof feature !== "object" || !("status" in feature) || !("source" in feature)) return false;
          return !featureValid(feature as RawFeatureValue, value.decisionAt!);
        }) || row.native.some(native => Object.values(native).some(feature =>
          feature && typeof feature === "object" && "status" in feature && "source" in feature &&
          !featureValid(feature as RawFeatureValue, value.decisionAt!)) ||
          Object.values(native.oiChange).some(feature => !featureValid(feature, value.decisionAt!)) ||
          Object.values(native.returnPct).some(feature => !featureValid(feature, value.decisionAt!))))) {
    throw new Error("候補データの時刻・対象・品質が不正です");
  }
  return value.rankingCutoff !== null && now - value.rankingCutoff > 150_000 && value.status !== "unavailable"
    ? { ...value, status: "stale", reason: value.reason ?? "discovery_stale" } : value;
}
function featureValid(feature: RawFeatureValue, decisionAt: number) {
  return (feature.value === null || Number.isFinite(feature.value)) &&
    (feature.status === "ready" ? feature.value !== null && feature.reason === null
    : feature.value === null && !!feature.reason) &&
    [feature.startAt, feature.endAt, feature.observedAt].every(time => time === null || Number.isSafeInteger(time) && time <= decisionAt) &&
    (feature.startAt === null || feature.endAt === null || feature.startAt <= feature.endAt) &&
    feature.observations.every(observation => [observation.startAt, observation.endAt, observation.observedAt,
      observation.sourceAt].every(time => time === null || Number.isSafeInteger(time) && time <= decisionAt));
}
export function discoveryTarget(row: DiscoveryRow): FavoriteTarget | null {
  return row.referenceKey && row.originals.length && row.originals.every(original => original.current)
    ? { kind: "reference", id: row.assetId, referenceKey: row.referenceKey,
      originals: row.originals.map(original => `${original.instrumentId}:${original.versionId}`).sort() } : null;
}
export function sameTarget(left: FavoriteTarget, right: FavoriteTarget | null) {
  if (!right || left.kind !== right.kind || left.id !== right.id) return false;
  if (left.kind === "instrument" && right.kind === "instrument") return left.version === right.version;
  return left.kind === "reference" && right.kind === "reference" && left.referenceKey === right.referenceKey &&
    JSON.stringify([...left.originals].sort()) === JSON.stringify([...right.originals].sort());
}
export function comparisonPin(row: DiscoveryRow): ComparisonPin | null {
  const target = discoveryTarget(row);
  return target ? { target, episodeId: row.episodeId, discoveredAt: row.raw.decisionAt,
    snapshot: { asset: row.asset, identityKey: row.identityKey, state: row.state, direction: row.direction,
      referenceClose: row.raw.referenceClose, referenceReturn15M: row.raw.referenceReturn15M,
      turnoverComparison: row.turnoverComparison } } : null;
}

/** Validate frozen UI evidence without refreshing or replacing it with current data. */
export function isDecisionEvidence(input: import("$lib/market/decisions").DecisionInput) {
  const snapshot = input.snapshot;
  if (!Number.isSafeInteger(snapshot.displayedAt) || Number(snapshot.displayedAt) <= 0) return false;
  try {
    const response = parseDiscovery({ schemaVersion: "discovery-response-v1", policy: snapshot.policy,
      generationId: snapshot.generationId, decisionAt: snapshot.decisionAt, rankingCutoff: snapshot.rankingCutoff,
      inputs: null, status: snapshot.displayedStatus, reason: null, historyAvailableFrom: null,
      rows: [snapshot.row], episodes: [], nextCursor: null }, Number(snapshot.displayedAt));
    const row = response.rows[0];
    return row.episodeId === input.episodeId && sameTarget(input.target, discoveryTarget(row));
  } catch { return false; }
}
