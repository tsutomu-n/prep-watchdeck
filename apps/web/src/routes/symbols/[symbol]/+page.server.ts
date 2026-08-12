import { error } from "@sveltejs/kit";
import { createPastNoteRepository } from "$lib/server/past-note-repository";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

const rankingTimeframes = ["5m", "15m", "1h", "4h", "24h"] as const;

export async function load({ params, url }) {
  const requestedSymbol = params.symbol.toUpperCase();
  const requestedTimeframe = url.searchParams.get("tf") ?? "15m";
  const timeframe = rankingTimeframes.includes(requestedTimeframe as (typeof rankingTimeframes)[number])
    ? requestedTimeframe
    : "15m";

  try {
    const snapshotRepository = createSnapshotRepository();
    const [snapshot, pastNotes] = await Promise.all([
      snapshotRepository.latest(),
      createPastNoteRepository().list()
    ]);
    const row = snapshot.rows.find((item) => item.symbol.toUpperCase() === requestedSymbol);
    if (!row) {
      error(404, "symbol not found");
    }

    return {
      snapshot,
      row,
      timeframe,
      pastNotes: pastNotes.filter((note) => note.symbol.toUpperCase() === requestedSymbol)
    };
  } catch (cause) {
    if (cause && typeof cause === "object" && "status" in cause) {
      throw cause;
    }
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
