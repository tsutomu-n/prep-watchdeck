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
  view: "native" | "reference";
  capturedAt: string;
  metricGenerationId: string | null;
  oi15mPct: number | null;
  trade15mPct: number | null;
  reference?: ReferenceNoteContext;
};

export type ReferenceNoteContext = {
  source: "bybit" | "binance";
  symbol: string;
  revision: string;
  cutoff: string;
  period: "15m" | "1h" | "24h" | "daily";
  dailyReferenceJst: string;
  stale: boolean;
  returnPct: number | null;
  quoteTurnover: number | null;
  close: number | null;
  turnoverRatio: number | null;
  dayPosition: number | null;
};

function finiteOrNull(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isReference(value: unknown): value is ReferenceNoteContext {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const ref = value as Record<string, unknown>;
  return Object.keys(ref).every(key => ["source", "symbol", "revision", "cutoff", "period",
    "dailyReferenceJst", "stale", "returnPct", "quoteTurnover", "close", "turnoverRatio", "dayPosition"].includes(key)) &&
    typeof ref.source === "string" && ["bybit", "binance"].includes(ref.source) &&
    typeof ref.symbol === "string" && /^[A-Za-z0-9_.-]{1,100}$/.test(ref.symbol) &&
    typeof ref.revision === "string" && ref.revision.length > 0 && ref.revision.length <= 160 &&
    typeof ref.cutoff === "string" && Number.isFinite(Date.parse(ref.cutoff)) &&
    typeof ref.period === "string" && ["15m", "1h", "24h", "daily"].includes(ref.period) &&
    typeof ref.dailyReferenceJst === "string" && /^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(ref.dailyReferenceJst) &&
    typeof ref.stale === "boolean" &&
    ["returnPct", "quoteTurnover", "close", "turnoverRatio", "dayPosition"].every(key => finiteOrNull(ref[key]));
}

export function isMarketPastNoteContext(value: unknown): value is MarketPastNoteContext {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const context = value as Partial<MarketPastNoteContext>;
  return Object.keys(context).every((key) => [
    "kind", "venueInstrumentId", "venueInstrumentVersionId", "view", "capturedAt",
    "metricGenerationId", "oi15mPct", "trade15mPct", "reference"
  ].includes(key)) && context.kind === "ui-observation-v1" && (context.view === "native" ? context.reference === undefined :
      context.view === "reference" && isReference(context.reference) &&
      context.oi15mPct === null && context.trade15mPct === null) &&
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
    (note.context === undefined || (isMarketPastNoteContext(note.context) &&
      note.context.venueInstrumentId === note.venueInstrumentId))
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
