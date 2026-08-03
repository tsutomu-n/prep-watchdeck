import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { GET, POST } from "./+server";

const originalPastNotesDir = process.env.PREP_WATCHDECK_PAST_NOTES_DIR;

afterEach(() => {
  if (originalPastNotesDir === undefined) {
    delete process.env.PREP_WATCHDECK_PAST_NOTES_DIR;
  } else {
    process.env.PREP_WATCHDECK_PAST_NOTES_DIR = originalPastNotesDir;
  }
});

describe("/api/past-notes", () => {
  it("keeps the existing GET and POST envelope", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-past-note-route-"));
    process.env.PREP_WATCHDECK_PAST_NOTES_DIR = root;
    try {
      const empty = await GET();
      await expect(empty.json()).resolves.toEqual({ notes: [] });

      const saved = await POST(
        event("http://localhost/api/past-notes", {
          symbol: "altusdt",
          reason: "出来高",
          note: "見直し"
        })
      );
      expect(saved.status).toBe(200);
      await expect(saved.json()).resolves.toMatchObject({
        ok: true,
        notes: [{ symbol: "ALTUSDT", reason: "出来高", note: "見直し" }]
      });

      const current = await GET();
      await expect(current.json()).resolves.toMatchObject({
        notes: [{ symbol: "ALTUSDT", reason: "出来高", note: "見直し" }]
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("forbids non-localhost writes", async () => {
    await expect(
      POST(event("https://example.com/api/past-notes", { symbol: "ALTUSDT", note: "x" }))
    ).rejects.toMatchObject({ status: 403 });
  });

  it("rejects a missing symbol and an empty annotation", async () => {
    await expect(
      POST(event("http://localhost/api/past-notes", { reason: "出来高", note: "x" }))
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      POST(event("http://localhost/api/past-notes", { symbol: "ALTUSDT", reason: " ", note: " " }))
    ).rejects.toMatchObject({ status: 400 });
  });
});

function event(url: string, payload: unknown) {
  return {
    url: new URL(url),
    request: new Request(url, {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "content-type": "application/json" }
    })
  } as never;
}
