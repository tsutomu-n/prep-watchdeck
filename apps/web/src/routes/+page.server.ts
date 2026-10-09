import { createMarketArtifactRepository } from "$lib/server/market-artifact-repository";

export async function load({ url }: { url: URL }) {
  if (url.searchParams.get("mode") !== "native") return {};

  try {
    return { market: await createMarketArtifactRepository().latest() };
  } catch (cause) {
    return {
      marketError: cause instanceof Error ? cause.message : "market artifacts unavailable"
    };
  }
}
