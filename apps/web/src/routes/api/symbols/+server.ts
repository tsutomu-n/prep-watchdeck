import { error, json } from "@sveltejs/kit";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

export async function GET({ url }) {
  const category = url.searchParams.get("category") ?? undefined;
  try {
    return json(await createSnapshotRepository().symbols(category));
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
