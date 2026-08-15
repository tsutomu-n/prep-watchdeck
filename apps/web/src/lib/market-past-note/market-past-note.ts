export type MarketPastNote = {
  venueInstrumentId: string;
  reason: string;
  observedAt: string;
  expiresAt: string;
  note: string;
};

export function isMarketPastNote(value: unknown): value is MarketPastNote {
  if (!value || typeof value !== "object") return false;
  const note = value as Partial<MarketPastNote>;
  return (
    typeof note.venueInstrumentId === "string" &&
    typeof note.reason === "string" &&
    typeof note.observedAt === "string" &&
    typeof note.expiresAt === "string" &&
    typeof note.note === "string"
  );
}

export function marketPastNotesFromPayload(payload: unknown): MarketPastNote[] | null {
  if (!payload || typeof payload !== "object") return null;
  const notes = (payload as { notes?: unknown }).notes;
  return Array.isArray(notes) ? notes.filter(isMarketPastNote) : null;
}
