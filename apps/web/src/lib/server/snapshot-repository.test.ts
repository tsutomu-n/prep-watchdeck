import { mkdtempSync, readFileSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LocalFileSnapshotRepository } from "./snapshot-repository";

describe("LocalFileSnapshotRepository", () => {
  it("loads and validates a fixture snapshot", async () => {
    const repo = new LocalFileSnapshotRepository("../../fixtures/snapshots/basic.json");

    const snapshot = await repo.latest();

    expect(snapshot.source.dataSource).toBe("fixture");
    expect(snapshot.rows?.length).toBeGreaterThan(0);
  });

  it("reuses unchanged snapshot objects across repository instances", async () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-snapshot-cache-"));
    const snapshotPath = join(root, "latest.json");
    try {
      writeFileSync(snapshotPath, readFileSync("../../fixtures/snapshots/basic.json", "utf-8"), "utf-8");

      const first = await new LocalFileSnapshotRepository(snapshotPath).latest();
      const second = await new LocalFileSnapshotRepository(snapshotPath).latest();

      expect(second).toBe(first);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("invalidates cached snapshots when the file changes", async () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-snapshot-cache-"));
    const snapshotPath = join(root, "latest.json");
    try {
      writeFileSync(snapshotPath, readFileSync("../../fixtures/snapshots/basic.json", "utf-8"), "utf-8");
      const repo = new LocalFileSnapshotRepository(snapshotPath);

      await expect(repo.latest()).resolves.toMatchObject({
        source: { dataSource: "fixture" }
      });

      writeFileSync(snapshotPath, JSON.stringify({ schemaVersion: 1 }) + "\n", "utf-8");
      const changedAt = new Date(Date.now() + 1000);
      utimesSync(snapshotPath, changedAt, changedAt);

      await expect(repo.latest()).rejects.toThrow("invalid scanner snapshot");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
