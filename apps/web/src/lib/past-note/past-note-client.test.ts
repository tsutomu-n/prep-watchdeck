import { afterEach, describe, expect, it, vi } from "vitest";
import type { PastNote } from "./past-note";
import { savePastNoteRecord } from "./past-note-client";

const note: PastNote = {
  symbol: "ALTUSDT",
  reason: "出来高",
  observedAt: "2026-06-24T00:00:00.000Z",
  expiresAt: "2026-08-24T00:00:00.000Z",
  note: "見直し"
};

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("past note API client", () => {
  it("posts to the existing endpoint and parses the notes envelope", async () => {
    const fetchMock = mockFetch({ notes: [note] });

    await expect(
      savePastNoteRecord({ symbol: "ALTUSDT", reason: "出来高", note: "見直し" })
    ).resolves.toEqual([note]);
    expect(fetchMock).toHaveBeenCalledWith("/api/past-notes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ symbol: "ALTUSDT", reason: "出来高", note: "見直し" })
    });
  });

  it("rejects non-ok responses and malformed success envelopes", async () => {
    mockFetchText("bad request", 400);
    await expect(
      savePastNoteRecord({ symbol: "ALTUSDT", reason: "出来高", note: "" })
    ).rejects.toThrow("bad request");

    mockFetch({ ok: true });
    await expect(
      savePastNoteRecord({ symbol: "ALTUSDT", reason: "出来高", note: "" })
    ).rejects.toThrow("invalid past notes response");
  });
});

function mockFetch(payload: unknown) {
  const fetchMock = vi.fn(async () => jsonResponse(payload));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function mockFetchText(text: string, status: number) {
  const fetchMock = vi.fn(async () => new Response(text, { status }));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" }
  });
}
