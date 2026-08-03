import { describe, expect, it } from "vitest";
import {
  filterPastNotesBySymbol,
  isPastNote,
  pastNotesFromPayload,
  type PastNote
} from "./past-note";

const note: PastNote = {
  symbol: "ALTUSDT",
  reason: "出来高",
  observedAt: "2026-06-24T00:00:00.000Z",
  expiresAt: "2026-08-24T00:00:00.000Z",
  note: "見直し"
};

describe("past note domain", () => {
  it("accepts the existing storage shape and rejects incomplete notes", () => {
    expect(isPastNote(note)).toBe(true);
    expect(isPastNote({ ...note, expiresAt: undefined })).toBe(false);
    expect(isPastNote(null)).toBe(false);
  });

  it("parses the existing notes envelope while filtering invalid entries", () => {
    expect(pastNotesFromPayload({ notes: [note, { ...note, note: 1 }] })).toEqual([note]);
    expect(pastNotesFromPayload({ notes: "invalid" })).toBeNull();
    expect(pastNotesFromPayload(null)).toBeNull();
  });

  it("filters symbols case-insensitively", () => {
    const lowerCaseNote = { ...note, symbol: "altusdt", reason: "lower" };
    const otherNote = { ...note, symbol: "BTCUSDT", reason: "other" };

    expect(filterPastNotesBySymbol([note, lowerCaseNote, otherNote], "AlTuSdT")).toEqual([
      note,
      lowerCaseNote
    ]);
  });
});
