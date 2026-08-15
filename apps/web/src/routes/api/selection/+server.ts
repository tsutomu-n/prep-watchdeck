import { error, json } from "@sveltejs/kit";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import { createSelectionCommandRepository } from "$lib/server/selection-command-repository";
import type { RequestEvent } from "./$types";

export async function POST(event: RequestEvent) {
  if (!isLocalhostRequest(event)) {
    error(403, "selection is only available from localhost");
  }
  try {
    const payload: unknown = await event.request.json();
    const { groupId, venueInstrumentId } = parseSelectionPayload(payload);
    return json({
      ok: true,
      command: await createSelectionCommandRepository().write(groupId, venueInstrumentId)
    });
  } catch (cause) {
    error(400, cause instanceof Error ? cause.message : "invalid selection");
  }
}

function parseSelectionPayload(payload: unknown) {
  if (!payload || typeof payload !== "object") throw new Error("invalid selection payload");
  const value = payload as Record<string, unknown>;
  const groupId = typeof value.groupId === "string" ? value.groupId.trim() : "";
  const venueInstrumentId =
    typeof value.venueInstrumentId === "string" ? value.venueInstrumentId.trim() : "";
  if (!groupId || !venueInstrumentId) {
    throw new Error("groupId and venueInstrumentId are required");
  }
  return { groupId, venueInstrumentId };
}
