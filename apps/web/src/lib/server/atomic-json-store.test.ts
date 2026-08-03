import { mkdtemp, readFile, readdir, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { describe, expect, it } from "vitest";
import { cleanupStaleAtomicTemps, writeJsonFileAtomic } from "./atomic-json-store";

describe("atomic json store", () => {
  it("writes JSON through a temp file and final rename", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-atomic-json-"));
    try {
      const path = join(root, "current.json");
      await writeJsonFileAtomic(path, { memos: [{ id: "memo-1" }] });

      await expect(readFile(path, "utf-8")).resolves.toBe(
        `${JSON.stringify({ memos: [{ id: "memo-1" }] }, null, 2)}\n`
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("keeps the current file intact when writing fails before replace", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-atomic-json-"));
    try {
      const path = join(root, "current.json");
      await writeFile(path, `${JSON.stringify({ memos: [{ id: "old" }] }, null, 2)}\n`, "utf-8");

      await expect(
        writeJsonFileAtomic(path, { memos: [{ id: "new" }] }, {
          beforeRename: () => {
            throw new Error("planned write failure");
          }
        })
      ).rejects.toThrow("planned write failure");

      const persisted = JSON.parse(await readFile(path, "utf-8"));
      expect(persisted).toEqual({ memos: [{ id: "old" }] });
      const leftovers = (await readdir(root)).filter((entry) => entry.endsWith(".tmp"));
      expect(leftovers).toEqual([]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("cleans stale temp files for the same target only", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-atomic-json-"));
    try {
      const path = join(root, "current.json");
      const staleTmp = join(root, `.${basename(path)}.stale.tmp`);
      const otherTmp = join(root, ".other.json.stale.tmp");
      await writeFile(staleTmp, "stale", "utf-8");
      await writeFile(otherTmp, "other", "utf-8");
      await utimes(staleTmp, new Date(0), new Date(0));
      await utimes(otherTmp, new Date(0), new Date(0));

      await cleanupStaleAtomicTemps(path, { staleTmpMs: 1000, now: () => 2000 });

      const entries = await readdir(root);
      expect(entries).not.toContain(basename(staleTmp));
      expect(entries).toContain(basename(otherTmp));
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
