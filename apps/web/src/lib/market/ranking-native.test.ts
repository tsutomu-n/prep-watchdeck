import { expect, test } from "vitest";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { rankingFixture } from "./ranking-test-fixture";
import { referenceNativeCandidates } from "./ranking-native";

test("lazy native links require a fresh, active, unique exact contract version", () => {
  const now = Date.parse("2026-10-09T03:00:00Z");
  const row = rankingFixture(undefined, now).rows.find(row => row.asset === "BTC")!;
  const snapshot = {
    generatedAt: new Date(now).toISOString(), items: [{ venue: "bitget", active: true,
      venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1, sourceSymbol: "BTCUSDT" }]
  } as UniverseSnapshotArtifact;
  expect(referenceNativeCandidates(row, snapshot, now)).toEqual(snapshot.items);
  expect(referenceNativeCandidates(row, null, now)).toEqual([]);
  expect(referenceNativeCandidates(row, snapshot, now + 120_001)).toEqual([]);
  expect(referenceNativeCandidates(row, snapshot, now - 1001)).toEqual([]);
  for (const change of [
    { active: false }, { venueInstrumentVersionId: 2 }, { sourceSymbol: "OTHER" }, { venue: "aster" as const }
  ]) expect(referenceNativeCandidates(row,
    { ...snapshot, items: [{ ...snapshot.items[0], ...change }] }, now)).toEqual([]);
  expect(referenceNativeCandidates(row, { ...snapshot, items: [...snapshot.items, ...snapshot.items] }, now)).toEqual([]);
});
