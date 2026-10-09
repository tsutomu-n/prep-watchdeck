import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";
import type { DecisionInput } from "$lib/market/decisions";
import { episodeSkipped } from "$lib/market/decisions";
import { LocalFileDecisionRepository, DECISION_MAX_BYTES } from "./decision-repository";

const input: DecisionInput = { id: "first", action: "skip", reason: "板を確認して見送り", episodeId: "episode-1",
  target: { kind: "reference", id: "asset:BTC", referenceKey: "bybit:BTCUSDT:v1", originals: ["mexc:BTC_USDT:1"] },
  snapshot: { source: "bybit", unit: "USDT", observedAt: 123, value: 100, quality: "stale" } };

test("manual decisions are durable, atomic, idempotent and episode-specific with a revision conflict", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-decisions-"));
  const path = join(root, "decisions.json");
  const repository = new LocalFileDecisionRepository(path, () => new Date("2026-10-10T00:00:00Z"));
  try {
    const saved = await repository.save(input, 0);
    expect(await repository.save(input, 0)).toEqual(saved); // Retry after a lost response.
    expect(saved.decisions[0].snapshot).toEqual(input.snapshot);
    expect(episodeSkipped(saved, "episode-1")).toBe(true);
    expect(episodeSkipped(saved, "episode-2")).toBe(false);
    const conflicting = await Promise.allSettled([
      repository.save({ ...input, id: "second", action: "watch" }, 1),
      repository.save({ ...input, id: "third" }, 1)
    ]);
    expect(conflicting.filter(item => item.status === "fulfilled")).toHaveLength(1);
    const failure = conflicting.find(item => item.status === "rejected") as PromiseRejectedResult;
    expect(failure.reason).toMatchObject({ status: 409 });
    expect((await new LocalFileDecisionRepository(path, () => new Date("2040-01-01")).read()).decisions).toHaveLength(2);
    await expect(repository.save({ ...input, reason: "different" }, 2)).rejects.toMatchObject({ status: 409 });
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("1000 decisions and 16MiB reject new records without deleting existing evidence", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-decisions-cap-"));
  const path = join(root, "decisions.json");
  const repository = new LocalFileDecisionRepository(path);
  try {
    const record = { ...input, recordedAt: "2026-10-10T00:00:00Z" };
    for (const size of [0, 17_000]) {
      const count = size ? 950 : 1000;
      const payload = { schemaVersion: 1, revision: count, decisions: Array.from({ length: count }, (_, index) =>
        ({ ...record, id: `record-${index}`, snapshot: size ? { data: "x".repeat(size) } : record.snapshot })) };
      const bytes = `${JSON.stringify(payload, null, 2)}\n`;
      expect(Buffer.byteLength(bytes)).toBeLessThan(DECISION_MAX_BYTES);
      await writeFile(path, bytes);
      const addition = size ? { ...input, snapshot: { data: "x".repeat(131_000) } } : input;
      if (size) {
        // Bring the repository just below its byte cap using valid, retained manual snapshots.
        const padding = Math.floor((DECISION_MAX_BYTES - Buffer.byteLength(bytes) - 1000) / count);
        for (const entry of payload.decisions) entry.snapshot = { data: "x".repeat(17_000 + padding) };
        await writeFile(path, `${JSON.stringify(payload, null, 2)}\n`);
      }
      const before = await readFile(path, "utf-8");
      await expect(repository.save(addition, count)).rejects.toMatchObject({ status: 413 });
      expect(await readFile(path, "utf-8")).toBe(before);
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});
