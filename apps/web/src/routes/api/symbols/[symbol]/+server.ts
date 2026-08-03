import { error, json } from "@sveltejs/kit";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

export async function GET({ params }) {
  try {
    const row = await createSnapshotRepository().symbol(params.symbol);
    if (!row) {
      error(404, "symbol not found");
    }
    return json(row);
  } catch (cause) {
    if (cause && typeof cause === "object" && "status" in cause) {
      throw cause;
    }
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
