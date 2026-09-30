import { json } from "@sveltejs/kit";
import { readCandleRecoveryState } from "$lib/server/candle-recovery-repository";
import { StateFileError } from "$lib/server/bounded-state-json";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import type { RequestEvent } from "./$types";

const headers = { "cache-control": "no-store" };

export async function GET(event: RequestEvent) {
  if (!isLocalhostRequest(event)) return json({ error: "localhost_required" }, { status: 403, headers });
  if ([...event.url.searchParams.keys()].length) {
    return json({ error: "invalid_query" }, { status: 400, headers });
  }
  try {
    const recovery = await readCandleRecoveryState();
    return json({ state: "available", recovery, errorCode: null }, { headers });
  } catch (cause) {
    if (cause instanceof StateFileError && cause.kind === "missing") {
      return json({ state: "not_run", recovery: null, errorCode: null }, { headers });
    }
    return json({ state: "unavailable", recovery: null,
      errorCode: "recovery_state_unavailable" }, { status: 503, headers });
  }
}
