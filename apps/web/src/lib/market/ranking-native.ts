import type { RankedRow } from "$lib/generated/ranking-response";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";

export function nativeUniverseFresh(universe: UniverseSnapshotArtifact | null, now: number): boolean {
  const age = universe ? now - Date.parse(universe.generatedAt) : NaN;
  return Number.isFinite(age) && age >= -1000 && age <= 120_000;
}

/** Links and note targets require the current, unambiguous original contract version. */
export function referenceNativeCandidates(
  row: RankedRow | null, universe: UniverseSnapshotArtifact | null, now: number
) {
  if (!row || !universe || !nativeUniverseFresh(universe, now)) return [];
  return row.originals.flatMap(original => {
    const matches = universe.items.filter(item => item.venue === original.venue
      && item.venueInstrumentId === original.instrumentId);
    if (matches.length !== 1) return [];
    const item = matches[0];
    return item.active && item.venueInstrumentVersionId === original.versionId
      && item.sourceSymbol === original.symbol ? [item] : [];
  });
}
