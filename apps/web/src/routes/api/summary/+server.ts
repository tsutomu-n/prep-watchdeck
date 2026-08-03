import { error, json } from "@sveltejs/kit";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

export async function GET() {
  try {
    return json(await createSnapshotRepository().summary());
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
