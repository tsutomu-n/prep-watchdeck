export type PastNote = {
  symbol: string;
  reason: string;
  observedAt: string;
  expiresAt: string;
  note: string;
};

export function isPastNote(value: unknown): value is PastNote {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<PastNote>;
  return (
    typeof candidate.symbol === "string" &&
    typeof candidate.reason === "string" &&
    typeof candidate.observedAt === "string" &&
    typeof candidate.expiresAt === "string" &&
    typeof candidate.note === "string"
  );
}

export function pastNotesFromPayload(payload: unknown) {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { notes?: unknown[] }).notes)) {
    return null;
  }
  return (payload as { notes: unknown[] }).notes.filter(isPastNote);
}

export function filterPastNotesBySymbol(notes: PastNote[], symbol: string) {
  const normalized = symbol.toUpperCase();
  return notes.filter((note) => note.symbol.toUpperCase() === normalized);
}
