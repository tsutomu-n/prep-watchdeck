import { json } from "@sveltejs/kit";
import { isLocalhostRequest, LocalRequestError, readLocalJson } from "$lib/server/localhost-request";
import { createMarketArtifactRepository } from "$lib/server/market-artifact-repository";
import { createMarketPastNoteRepository, PastNoteError } from "$lib/server/market-past-note-repository";
import { isMarketPastNoteContext } from "$lib/market-past-note/market-past-note";
import type { RequestEvent } from "./$types";

const headers = { "cache-control": "no-store" };

export async function GET(event: RequestEvent) {
  if (!isLocalhostRequest(event)) return fail(403, "localhost_required");
  const keys = [...event.url.searchParams.keys()];
  if (keys.length !== 1 || keys[0] !== "venueInstrumentId") return fail(400, "invalid_query");
  const id = event.url.searchParams.get("venueInstrumentId") ?? "";
  try {
    return json(await createMarketPastNoteRepository().list(id), { headers });
  } catch (cause) {
    return failure(cause);
  }
}

export async function POST(event: RequestEvent) {
  try {
    const payload = await readLocalJson(event);
    const value = parsePayload(payload);
    const { universe } = await createMarketArtifactRepository().latest();
    const instrument = universe.items.find((item) => item.venueInstrumentId === value.venueInstrumentId);
    if (!instrument?.active || instrument.venueInstrumentVersionId !== value.venueInstrumentVersionId) {
      return fail(409, "past_note_instrument_changed");
    }
    const result = await createMarketPastNoteRepository().save(
      value.venueInstrumentId, value.reason, value.note, value.expectedRevisionToken,
      value.context
    );
    return json({ ok: true, ...result }, { headers });
  } catch (cause) {
    return failure(cause);
  }
}

function parsePayload(payload: unknown) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new LocalRequestError(400, "invalid_past_note");
  }
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).some((key) => ![
    "venueInstrumentId", "venueInstrumentVersionId", "reason", "note", "expectedRevisionToken", "context"
  ].includes(key))) throw new LocalRequestError(400, "invalid_past_note");
  if (typeof value.venueInstrumentId !== "string" ||
      !Number.isSafeInteger(value.venueInstrumentVersionId) ||
      typeof value.reason !== "string" || typeof value.note !== "string" ||
      typeof value.expectedRevisionToken !== "string" ||
      !/^(?:absent|[0-9a-f]{64})$/.test(value.expectedRevisionToken) ||
      Number(value.venueInstrumentVersionId) < 1 || value.reason.length > 200 ||
      value.note.length > 10_000 || (!value.reason.trim() && !value.note.trim())) {
    throw new LocalRequestError(400, "invalid_past_note");
  }
  if (value.context !== undefined && (
    !isMarketPastNoteContext(value.context) ||
    value.context.venueInstrumentId !== value.venueInstrumentId ||
    value.context.venueInstrumentVersionId !== value.venueInstrumentVersionId ||
    (value.context.metricGenerationId?.length ?? 0) > 160 ||
    Math.abs(Date.now() - Date.parse(value.context.capturedAt)) > 5 * 60_000
  )) throw new LocalRequestError(400, "invalid_past_note_context");
  return {
    venueInstrumentId: value.venueInstrumentId,
    venueInstrumentVersionId: value.venueInstrumentVersionId,
    reason: value.reason.trim(),
    note: value.note.trim(),
    expectedRevisionToken: value.expectedRevisionToken,
    context: value.context
  };
}

function fail(status: number, code: string) {
  return json({ error: code }, { status, headers });
}

function failure(cause: unknown) {
  if (cause instanceof LocalRequestError || cause instanceof PastNoteError) {
    return fail(cause.status, cause.code);
  }
  return fail(500, "past_note_unavailable");
}
