import { error, json } from "@sveltejs/kit";
import { createPastNote, createPastNoteRepository } from "$lib/server/past-note-repository";
import type { RequestEvent } from "./$types";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

export async function GET() {
  try {
    return json({ notes: await createPastNoteRepository().list() });
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "past notes unavailable");
  }
}

export async function POST(event: RequestEvent) {
  if (!LOCAL_HOSTS.has(event.url.hostname)) {
    error(403, "past notes are only available from localhost");
  }

  try {
    const payload: unknown = await event.request.json();
    const { symbol, reason, note } = parsePayload(payload);
    return json({
      ok: true,
      notes: await createPastNoteRepository().save(createPastNote(symbol, reason, note))
    });
  } catch (cause) {
    error(400, cause instanceof Error ? cause.message : "invalid past note");
  }
}

function parsePayload(payload: unknown) {
  if (!payload || typeof payload !== "object") {
    throw new Error("invalid past note payload");
  }

  const candidate = payload as Record<string, unknown>;
  const symbol = typeof candidate.symbol === "string" ? candidate.symbol.trim().toUpperCase() : "";
  const reason = typeof candidate.reason === "string" ? candidate.reason.trim() : "";
  const note = typeof candidate.note === "string" ? candidate.note.trim() : "";

  if (!symbol) {
    throw new Error("symbol is required");
  }
  if (!reason && !note) {
    throw new Error("reason or note is required");
  }

  return { symbol, reason, note };
}
