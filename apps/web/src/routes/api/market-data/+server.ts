import { error, json } from "@sveltejs/kit";
import { createMarketArtifactRepository } from "$lib/server/market-artifact-repository";

export async function GET() {
  try {
    return json(await createMarketArtifactRepository().latest(), {
      headers: { "cache-control": "no-store" }
    });
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "market artifacts unavailable");
  }
}
