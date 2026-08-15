import { createMarketArtifactRepository } from "$lib/server/market-artifact-repository";

export async function load() {
  try {
    return { market: await createMarketArtifactRepository().latest() };
  } catch (cause) {
    return {
      marketError: cause instanceof Error ? cause.message : "market artifacts unavailable"
    };
  }
}
