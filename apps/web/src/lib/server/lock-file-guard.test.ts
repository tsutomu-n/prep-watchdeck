import { mkdtemp, readFile, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LockFileTimeoutError, withLockFile } from "./lock-file-guard";

describe("lock file guard", () => {
  it("creates and releases a lock around a task", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-lock-"));
    try {
      const lockPath = join(root, "current.json.lock");
      await withLockFile(lockPath, async () => {
        const payload = JSON.parse(await readFile(lockPath, "utf-8"));
        expect(payload.pid).toBe(process.pid);
      });

      await expect(readFile(lockPath, "utf-8")).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("times out when a fresh lock remains", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-lock-"));
    try {
      const lockPath = join(root, "current.json.lock");
      await writeFile(lockPath, "fresh", "utf-8");

      await expect(
        withLockFile(lockPath, async () => "unreachable", {
          timeoutMs: 0,
          staleMs: 60_000,
          now: () => 0,
          sleep: async () => undefined
        })
      ).rejects.toBeInstanceOf(LockFileTimeoutError);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("removes stale locks and proceeds", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-lock-"));
    try {
      const lockPath = join(root, "current.json.lock");
      await writeFile(lockPath, "stale", "utf-8");
      await utimes(lockPath, new Date(0), new Date(0));

      await expect(
        withLockFile(lockPath, async () => "ok", {
          staleMs: 1000,
          now: () => 2000,
          sleep: async () => undefined
        })
      ).resolves.toBe("ok");
      await expect(readFile(lockPath, "utf-8")).rejects.toMatchObject({ code: "ENOENT" });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("does not release a lock that was replaced by another owner", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-lock-"));
    try {
      const lockPath = join(root, "current.json.lock");
      await withLockFile(lockPath, async () => {
        await writeFile(
          lockPath,
          JSON.stringify({ pid: process.pid, token: "other-owner", createdAt: new Date(0).toISOString() }) + "\n",
          "utf-8"
        );
      });

      const payload = JSON.parse(await readFile(lockPath, "utf-8"));
      expect(payload.token).toBe("other-owner");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
