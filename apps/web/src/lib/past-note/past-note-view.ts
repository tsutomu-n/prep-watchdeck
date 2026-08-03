import type { PastNote } from "./past-note";

export function pastNoteSummary(note: Pick<PastNote, "reason" | "note">) {
  return `銘柄注記: ${note.reason}${note.note ? ` - ${note.note}` : ""}`;
}
