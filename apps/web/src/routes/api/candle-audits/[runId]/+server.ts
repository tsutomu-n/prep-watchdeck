import { json } from "@sveltejs/kit";
import { readCandleAuditDetail } from "$lib/server/candle-audit-repository";
import { StateFileError } from "$lib/server/bounded-state-json";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import type { RequestEvent } from "./$types";

const headers = { "cache-control": "no-store" };

function failure(status: number, code: string) {
  return json({ errorCode: code }, { status, headers });
}

export async function GET(event: RequestEvent) {
  if (!await isLocalhostRequest(event)) return failure(403, "localhost_required");
  const parameters = [...event.url.searchParams.entries()];
  if (parameters.some(([key]) => key !== "offset" && key !== "limit") ||
      new Set(parameters.map(([key]) => key)).size !== parameters.length) {
    return failure(400, "audit_invalid_request");
  }
  const offsetText = event.url.searchParams.get("offset") ?? "0";
  const limitText = event.url.searchParams.get("limit") ?? "200";
  if (!/^(?:0|[1-9]\d*)$/.test(offsetText) || !/^[1-9]\d*$/.test(limitText)) {
    return failure(400, "audit_invalid_request");
  }
  const offset = Number(offsetText);
  const limit = Number(limitText);
  try {
    return json(await readCandleAuditDetail(event.params.runId, { offset, limit }), { headers });
  } catch (cause) {
    if (cause instanceof Error && cause.message === "audit_invalid_request") {
      return failure(400, "audit_invalid_request");
    }
    if (cause instanceof StateFileError && cause.kind === "missing") {
      return failure(404, "audit_report_not_found");
    }
    return failure(503, "audit_report_unavailable");
  }
}
