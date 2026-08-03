import { error, json } from "@sveltejs/kit";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

export async function GET({ url }) {
  const tf = url.searchParams.get("tf") ?? "15m";
  const metric = url.searchParams.get("metric") ?? "changeUp";
  try {
    return json(await createSnapshotRepository().rankings(tf, metric));
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
