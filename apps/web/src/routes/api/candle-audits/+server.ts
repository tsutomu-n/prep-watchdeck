import { json } from "@sveltejs/kit";
import { readCandleAuditIndex } from "$lib/server/candle-audit-repository";
import { StateFileError } from "$lib/server/bounded-state-json";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import type { RequestEvent } from "./$types";

const headers = { "cache-control": "no-store" };

export async function GET(event: RequestEvent) {
  if (!await isLocalhostRequest(event)) return json({ error: "localhost_required" }, { status: 403, headers });
  if ([...event.url.searchParams.keys()].length) {
    return json({ error: "audit_invalid_request" }, { status: 400, headers });
  }
  try {
    const index = await readCandleAuditIndex();
    return json({ state: "available", index, errorCode: null }, { headers });
  } catch (cause) {
    if (cause instanceof StateFileError && cause.kind === "missing") {
      return json({ state: "not_run", index: null, errorCode: null }, { headers });
    }
    return json({ state: "unavailable", index: null,
      errorCode: "audit_index_unavailable" }, { status: 503, headers });
  }
}
