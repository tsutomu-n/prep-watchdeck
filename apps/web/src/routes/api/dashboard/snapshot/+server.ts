import { error, json } from "@sveltejs/kit";
import { slimSnapshotForDashboard } from "$lib/server/dashboard-snapshot";
import { createSnapshotRepository } from "$lib/server/snapshot-repository";

const noStoreHeaders = { "cache-control": "no-store" };

export async function GET({ url }) {
  try {
    const snapshot = await createSnapshotRepository().latest();
    if (url.searchParams.get("afterRunId") === snapshot.runId) {
      return new Response(null, { status: 204, headers: noStoreHeaders });
    }
    return json(slimSnapshotForDashboard(snapshot), { headers: noStoreHeaders });
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "snapshot unavailable");
  }
}
