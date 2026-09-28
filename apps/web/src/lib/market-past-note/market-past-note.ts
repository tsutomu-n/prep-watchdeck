export type MarketPastNote = {
  venueInstrumentId: string;
  reason: string;
  observedAt: string;
  expiresAt: string;
  note: string;
  context?: MarketPastNoteContext;
};

export type MarketPastNoteContext = {
  kind: "ui-observation-v1";
  venueInstrumentId: string;
  venueInstrumentVersionId: number;
  view: "native";
  capturedAt: string;
  metricGenerationId: string | null;
  oi15mPct: number | null;
  trade15mPct: number | null;
};

export function isMarketPastNoteContext(value: unknown): value is MarketPastNoteContext {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const context = value as Partial<MarketPastNoteContext>;
  return Object.keys(context).every((key) => [
    "kind", "venueInstrumentId", "venueInstrumentVersionId", "view", "capturedAt",
    "metricGenerationId", "oi15mPct", "trade15mPct"
  ].includes(key)) && context.kind === "ui-observation-v1" && context.view === "native" &&
    typeof context.venueInstrumentId === "string" &&
    /^[a-z]+:[A-Za-z0-9_.-]+$/.test(context.venueInstrumentId) &&
    Number.isSafeInteger(context.venueInstrumentVersionId) &&
    Number(context.venueInstrumentVersionId) > 0 &&
    typeof context.capturedAt === "string" && Number.isFinite(Date.parse(context.capturedAt)) &&
    (context.metricGenerationId === null || (typeof context.metricGenerationId === "string" &&
      context.metricGenerationId.length <= 160)) &&
    (context.oi15mPct === null || (typeof context.oi15mPct === "number" && Number.isFinite(context.oi15mPct))) &&
    (context.trade15mPct === null || (typeof context.trade15mPct === "number" && Number.isFinite(context.trade15mPct)));
}

export function isMarketPastNote(value: unknown): value is MarketPastNote {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const note = value as Partial<MarketPastNote>;
  return (
    Object.keys(note).every((key) => [
      "venueInstrumentId", "reason", "observedAt", "expiresAt", "note", "context"
    ].includes(key)) &&
    typeof note.venueInstrumentId === "string" &&
    /^[a-z]+:[A-Za-z0-9_.-]+$/.test(note.venueInstrumentId) &&
    typeof note.reason === "string" && note.reason.length <= 200 &&
    typeof note.observedAt === "string" && Number.isFinite(Date.parse(note.observedAt)) &&
    typeof note.expiresAt === "string" && Number.isFinite(Date.parse(note.expiresAt)) &&
    Date.parse(note.expiresAt) > Date.parse(note.observedAt) &&
    typeof note.note === "string" && note.note.length <= 10_000 &&
    (note.context === undefined || isMarketPastNoteContext(note.context))
  );
}

export function marketPastNotesFromPayload(payload: unknown): MarketPastNote[] | null {
  if (!payload || typeof payload !== "object") return null;
  const notes = (payload as { notes?: unknown }).notes;
  return Array.isArray(notes) ? notes.filter(isMarketPastNote) : null;
}

export function pastNoteSnapshotFromPayload(payload: unknown) {
  const notes = marketPastNotesFromPayload(payload);
  const token = (payload as { revisionToken?: unknown } | null)?.revisionToken;
  return notes && typeof token === "string" && /^(?:absent|[0-9a-f]{64})$/.test(token)
    ? { notes, revisionToken: token } : null;
}
