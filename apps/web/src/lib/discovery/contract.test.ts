import { expect, test } from "vitest";
import { discoveryFixture } from "./discovery-test-fixture";
import { comparisonPin, discoveryTarget, isDecisionEvidence, parseDiscovery, sameTarget } from "./contract";

const now = Date.parse("2026-10-10T00:00:15Z");
test("Discovery keeps provenance, marks stale projections and fails closed on malformed/future values", () => {
  const fixture = discoveryFixture(now);
  expect(parseDiscovery(fixture, now)).toEqual(fixture);
  expect(parseDiscovery(fixture, now + 300_000).status).toBe("stale");
  const invalid = structuredClone(fixture);
  invalid.rows[0].raw.referenceClose.observedAt = now + 10_000;
  expect(() => parseDiscovery(invalid, now)).toThrow();
  invalid.rows[0].raw.referenceClose.observedAt = fixture.decisionAt;
  invalid.rows[0].raw.referenceClose.status = "stale";
  expect(() => parseDiscovery(invalid, now)).toThrow();
  expect(() => parseDiscovery({ ...fixture, policy: { ...fixture.policy, turnoverRatioThreshold: 2 } }, now)).toThrow();
});
test("a pin captures a target and detection evidence; source/original version changes require recheck", () => {
  const row = discoveryFixture(now).rows[0];
  const pin = comparisonPin(row)!;
  expect(sameTarget(pin.target, discoveryTarget(row))).toBe(true);
  const changed = structuredClone(row); changed.originals[0].versionId++;
  expect(sameTarget(pin.target, discoveryTarget(changed))).toBe(false);
  changed.originals[0].current = false;
  expect(discoveryTarget(changed)).toBeNull();
  expect(pin.snapshot.referenceClose).toEqual(row.raw.referenceClose);
});

test("manual decisions retain the displayed evidence and reject a different episode, target or observation", () => {
  const response = discoveryFixture(now);
  const row = response.rows[0];
  const input = { id: "manual", action: "skip" as const, reason: "確認", target: discoveryTarget(row)!, episodeId: row.episodeId!,
    snapshot: { row, displayedAt: now, displayedStatus: "stale", policy: response.policy,
      generationId: response.generationId, decisionAt: response.decisionAt, rankingCutoff: response.rankingCutoff } };
  expect(isDecisionEvidence(input)).toBe(true);
  expect(isDecisionEvidence({ ...input, episodeId: "different" })).toBe(false);
  expect(isDecisionEvidence({ ...input, target: { ...input.target, id: "asset:OTHER" } })).toBe(false);
  expect(isDecisionEvidence({ ...input, snapshot: { ...input.snapshot, decisionAt: now + 10000 } })).toBe(false);
});


test("overflowing JSON numbers are rejected before projection or immutable decision persistence", () => {
  for (const overflowing of ["1e400", "-1e400"]) {
    const fixture = discoveryFixture(now);
    const payload = JSON.parse(JSON.stringify(fixture).replace('"value":100,', `"value":${overflowing},`));
    expect(Number.isFinite(payload.rows[0].raw.referenceClose.value)).toBe(false);
    expect(() => parseDiscovery(payload, now)).toThrow();
    const row = payload.rows[0];
    expect(isDecisionEvidence({ id: "overflow", action: "watch", reason: "test", target: discoveryTarget(row)!,
      episodeId: row.episodeId!, snapshot: { row, displayedAt: now, displayedStatus: fixture.status, policy: fixture.policy,
        generationId: fixture.generationId, decisionAt: fixture.decisionAt, rankingCutoff: fixture.rankingCutoff } })).toBe(false);
  }
});
