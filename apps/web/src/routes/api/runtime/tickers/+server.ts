import { error, json } from "@sveltejs/kit";
import { createTickerRuntimeRepository } from "$lib/server/ticker-runtime-repository";

const noStoreHeaders = { "cache-control": "no-store" };

export async function GET({ url }) {
  const rawAfter = url.searchParams.get("after") ?? "0";
  if (!/^\d+$/.test(rawAfter)) {
    error(400, "invalid after sequence");
  }
  const afterSequence = Number(rawAfter);
  if (!Number.isSafeInteger(afterSequence)) {
    error(400, "invalid after sequence");
  }

  try {
    const batch = await createTickerRuntimeRepository().batchAfter(afterSequence);
    return batch
      ? json(batch, { headers: noStoreHeaders })
      : new Response(null, { status: 204, headers: noStoreHeaders });
  } catch (cause) {
    if (cause && typeof cause === "object" && "status" in cause) {
      throw cause;
    }
    error(503, cause instanceof Error ? cause.message : "ticker runtime unavailable");
  }
}
