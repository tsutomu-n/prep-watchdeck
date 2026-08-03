import { pastNotesFromPayload, type PastNote } from "./past-note";

const jsonHeaders = { "content-type": "application/json" };

export type PastNoteCreateRequest = {
  symbol: string;
  reason: string;
  note: string;
};

export async function savePastNoteRecord(request: PastNoteCreateRequest): Promise<PastNote[]> {
  const response = await fetch("/api/past-notes", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify(request)
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const notes = pastNotesFromPayload(await response.json());
  if (!notes) throw new Error("invalid past notes response");
  return notes;
}
