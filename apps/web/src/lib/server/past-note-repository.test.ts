import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { createPastNote, LocalFilePastNoteRepository } from "./past-note-repository";

describe("LocalFilePastNoteRepository", () => {
  it("creates the existing storage shape with an exact 60-day expiry", () => {
    expect(
      createPastNote("ALTUSDT", "前回急変", "出来高を再確認", new Date("2026-06-21T00:00:00.000Z"))
    ).toEqual({
      symbol: "ALTUSDT",
      reason: "前回急変",
      observedAt: "2026-06-21T00:00:00.000Z",
      expiresAt: "2026-08-20T00:00:00.000Z",
      note: "出来高を再確認"
    });
  });

  it("saves current notes and archives notes after the 60-day retention window", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-past-notes-"));
    try {
      const repo = new LocalFilePastNoteRepository(root, () => new Date("2026-06-21T00:00:00.000Z"));

      await repo.save({
        symbol: "OLDUSDT",
        reason: "old move",
        note: "archive me",
        observedAt: "2026-03-01T00:00:00.000Z",
        expiresAt: "2026-05-01T00:00:00.000Z"
      });
      await repo.save({
        symbol: "ALTUSDT",
        reason: "recent move",
        note: "keep me",
        observedAt: "2026-06-21T00:00:00.000Z",
        expiresAt: "2026-08-21T00:00:00.000Z"
      });

      const notes = await repo.list();
      expect(notes.map((note) => note.symbol)).toEqual(["ALTUSDT"]);

      const current = JSON.parse(await readFile(join(root, "current.json"), "utf-8"));
      expect(current.notes.map((note: { symbol: string }) => note.symbol)).toEqual(["ALTUSDT"]);

      const archive = JSON.parse(
        await readFile(join(root, "archive", "2026-03", "past-notes-2026-03.json"), "utf-8")
      );
      expect(archive.notes.map((note: { symbol: string }) => note.symbol)).toEqual(["OLDUSDT"]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("keeps separate notes for the same symbol when reasons differ", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-past-notes-"));
    try {
      const repo = new LocalFilePastNoteRepository(root, () => new Date("2026-06-21T00:00:00.000Z"));

      await repo.save({
        symbol: "ALTUSDT",
        reason: "manual",
        note: "operator note",
        observedAt: "2026-06-21T00:00:00.000Z",
        expiresAt: "2026-08-20T00:00:00.000Z"
      });
      await repo.save({
        symbol: "ALTUSDT",
        reason: "自動検出: 過去急変",
        note: "auto note",
        observedAt: "2026-06-21T01:00:00.000Z",
        expiresAt: "2026-08-20T01:00:00.000Z"
      });

      const notes = await repo.list();

      expect(notes.map((note) => note.reason)).toEqual(["自動検出: 過去急変", "manual"]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
