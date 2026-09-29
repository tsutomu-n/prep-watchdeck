import { chmod, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
      const pruned = await repository.save(ID, "新しい記録", "期限後", saved.revisionToken);
      expect(pruned.notes).toHaveLength(1);
      expect(JSON.parse(await readFile(path, "utf-8")).notes).toHaveLength(1);
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


test("invalid items, unknown schema and read permission failures never initialize notes", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-notes-boundary-"));
  const path = join(root, `${ID}.json`);
  const repository = new LocalFileMarketPastNoteRepository(root);
  try {
    for (const bytes of [JSON.stringify({ schemaVersion: 99, venueInstrumentId: ID, notes: [] }),
      JSON.stringify({ schemaVersion: 2, venueInstrumentId: ID, notes: [{ note: "invalid" }] })]) {
      await writeFile(path, bytes);
      await expect(repository.list(ID)).rejects.toMatchObject({ status: 500 });
      await expect(repository.save(ID, "保護", "上書きしない", "absent")).rejects.toMatchObject({ status: 500 });
      expect(await readFile(path, "utf-8")).toBe(bytes);
    }
    const before = await readFile(path);
    await chmod(path, 0o000);
    try {
      await expect(repository.list(ID)).rejects.toMatchObject({ status: 500, code: "past_note_unavailable" });
      await expect(repository.save(ID, "保護", "上書きしない", "absent")).rejects.toMatchObject({ status: 500 });
    } finally { await chmod(path, 0o600); }
    expect(await readFile(path)).toEqual(before);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("observation context rejects nonfinite values and unbounded nested data", async () => {
  const { isMarketPastNoteContext } = await import("$lib/market-past-note/market-past-note");
  const context = { kind: "ui-observation-v1", venueInstrumentId: ID, venueInstrumentVersionId: 1,
    view: "native", capturedAt: new Date().toISOString(), metricGenerationId: "g", oi15mPct: 10, trade15mPct: null };
  for (const value of [NaN, Infinity, -Infinity]) {
    expect(isMarketPastNoteContext({ ...context, oi15mPct: value })).toBe(false);
    expect(isMarketPastNoteContext({ ...context, trade15mPct: value })).toBe(false);
  }
  const reference = { source: "bybit", symbol: "BTCUSDT", revision: "r1", cutoff: new Date().toISOString(),
    period: "15m", dailyReferenceJst: "09:00", stale: false, returnPct: 2, quoteTurnover: 100,
    close: 100, turnoverRatio: null, dayPosition: 50 };
  const refContext = { ...context, view: "reference", oi15mPct: null, reference };
  expect(isMarketPastNoteContext(refContext)).toBe(true);
  for (const patch of [{ source: "unknown" }, { symbol: "x".repeat(101) }, { revision: "r".repeat(161) },
    { close: Infinity }, { cutoff: "invalid" }, { dailyReferenceJst: "24:00" }, { raw: "secret" },
    { metrics: Array(17).fill(1) }]) {
    expect(isMarketPastNoteContext({ ...refContext, reference: { ...reference, ...patch } })).toBe(false);
  }
});
