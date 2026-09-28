import { json } from "@sveltejs/kit";
import { LocalRequestError, readLocalJson } from "$lib/server/localhost-request";
import { createSelectionCommandRepository, SelectionError } from "$lib/server/selection-command-repository";
import type { RequestEvent } from "./$types";

export async function POST(event: RequestEvent) {
  const headers = { "cache-control": "no-store" };
  try {
    const payload = await readLocalJson(event);
    const command = parseSelectionPayload(payload);
    return json({
      ok: true,
      command: await createSelectionCommandRepository().execute(command)
    }, { headers });
  } catch (cause) {
    const failure = cause instanceof SelectionError || cause instanceof LocalRequestError
      ? cause : new SelectionError(500, "selection_unavailable");
    return json({ error: failure.code }, { status: failure.status, headers });
  }
}

function parseSelectionPayload(payload: unknown) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new LocalRequestError(400, "invalid_selection");
  }
  const value = payload as Record<string, unknown>;
  const action = value.action;
  const allowed = action === "heartbeat"
    ? ["action", "groupId", "venueInstrumentId", "venueInstrumentVersionId", "expectedRequestedAt"]
    : ["action", "groupId", "venueInstrumentId", "venueInstrumentVersionId"];
  if ((action !== "select" && action !== "heartbeat") ||
      Object.keys(value).some((key) => !allowed.includes(key)) ||
      typeof value.groupId !== "string" || !value.groupId.trim() ||
      typeof value.venueInstrumentId !== "string" || !value.venueInstrumentId.trim() ||
      !Number.isSafeInteger(value.venueInstrumentVersionId) ||
      Number(value.venueInstrumentVersionId) < 1 ||
      value.groupId.length > 160 || value.venueInstrumentId.length > 160 ||
      (action === "heartbeat" &&
        (typeof value.expectedRequestedAt !== "string" ||
          !Number.isFinite(Date.parse(value.expectedRequestedAt))))) {
    throw new LocalRequestError(400, "invalid_selection");
  }
  return {
    action: action as "select" | "heartbeat",
    groupId: value.groupId,
    venueInstrumentId: value.venueInstrumentId,
    venueInstrumentVersionId: value.venueInstrumentVersionId as number,
    expectedRequestedAt: action === "heartbeat" ? value.expectedRequestedAt as string : undefined
  };
}
