import { error, json } from "@sveltejs/kit";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import { createMarketPastNoteRepository } from "$lib/server/market-past-note-repository";
import type { RequestEvent } from "./$types";

export async function GET(event: RequestEvent) {
  const venueInstrumentId = event.url.searchParams.get("venueInstrumentId")?.trim() ?? "";
  if (!venueInstrumentId) error(400, "venueInstrumentId is required");
  try {
    return json({ notes: await createMarketPastNoteRepository().list(venueInstrumentId) });
  } catch (cause) {
    error(400, cause instanceof Error ? cause.message : "past notes unavailable");
  }
}

export async function POST(event: RequestEvent) {
  if (!isLocalhostRequest(event)) {
    error(403, "past notes are only available from localhost");
  }
  try {
    const payload: unknown = await event.request.json();
    const value = parsePayload(payload);
    return json({
      ok: true,
      notes: await createMarketPastNoteRepository().save(
        value.venueInstrumentId,
        value.reason,
        value.note
      )
    });
  } catch (cause) {
    error(400, cause instanceof Error ? cause.message : "invalid past note");
  }
}

function parsePayload(payload: unknown) {
  if (!payload || typeof payload !== "object") throw new Error("invalid past note payload");
  const value = payload as Record<string, unknown>;
  const venueInstrumentId =
    typeof value.venueInstrumentId === "string" ? value.venueInstrumentId.trim() : "";
  const reason = typeof value.reason === "string" ? value.reason.trim() : "";
  const note = typeof value.note === "string" ? value.note.trim() : "";
  if (!venueInstrumentId) throw new Error("venueInstrumentId is required");
  if (!reason && !note) throw new Error("reason or note is required");
  return { venueInstrumentId, reason, note };
}
