import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "vitest";
import { LocalFileMarketPastNoteRepository } from "./market-past-note-repository";

const ID = "bitget:BTCUSDT";

describe("past note file safety", () => {
  test("v1 notes survive an optional v2 observation save", async () => {
    const root = await mkdtemp(join(tmpdir(), "watchdeck-notes-v2-"));
    const path = join(root, `${ID}.json`);
    const now = new Date("2026-09-28T00:00:00.000Z");
    const repository = new LocalFileMarketPastNoteRepository(root, () => now);
    try {
      await writeFile(path, JSON.stringify({ schemaVersion: 1, venueInstrumentId: ID, notes: [{
        venueInstrumentId: ID, reason: "旧記録", note: "保全", observedAt: now.toISOString(),
        expiresAt: "2026-11-01T00:00:00.000Z"
      }] }));
      const before = await repository.list(ID);
      const result = await repository.save(ID, "新記録", "表示を観測", before.revisionToken, {
        kind: "ui-observation-v1", venueInstrumentId: ID, venueInstrumentVersionId: 7,
        view: "native", capturedAt: now.toISOString(), metricGenerationId: "fixture-1",
        oi15mPct: 10, trade15mPct: null
      });
      expect(result.notes).toHaveLength(2);
      expect(result.notes[1].note).toBe("保全");
      expect(JSON.parse(await readFile(path, "utf-8")).schemaVersion).toBe(2);
      expect((await repository.list(ID)).notes[0].context?.oi15mPct).toBe(10);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
  test("GET does not prune, CAS rejects a stale tab, and corruption is never replaced", async () => {
    const root = await mkdtemp(join(tmpdir(), "watchdeck-notes-"));
    const path = join(root, `${ID}.json`);
    let now = new Date("2026-09-28T00:00:00.000Z");
    const repository = new LocalFileMarketPastNoteRepository(root, () => now);
    try {
      const empty = await repository.list(ID);
      expect(empty).toEqual({ notes: [], revisionToken: "absent" });
      const saved = await repository.save(ID, "確認", "初回", empty.revisionToken);
      expect(saved.notes[0].note).toBe("初回");
      await expect(repository.save(ID, "確認", "古いタブ", empty.revisionToken))
        .rejects.toMatchObject({ status: 409, code: "past_note_conflict" });
      expect((await repository.list(ID)).notes[0].note).toBe("初回");
      now = new Date("2026-12-01T00:00:00.000Z");
      const bytes = await readFile(path);
      expect((await repository.list(ID)).notes).toEqual([]);
      expect(await readFile(path)).toEqual(bytes);
      await writeFile(path, "{bad", "utf-8");
      await expect(repository.list(ID)).rejects.toMatchObject({ status: 500 });
      await expect(repository.save(ID, "確認", "上書き", saved.revisionToken))
        .rejects.toMatchObject({ status: 500 });
      expect(await readFile(path, "utf-8")).toBe("{bad");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
