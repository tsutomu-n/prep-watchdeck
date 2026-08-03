import { mkdtemp, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

describe("LocalFileTickerRuntimeRepository", () => {
  it("returns 204 semantics, the immediate delta, and full gap recovery", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-runtime-"));
    const runtimePath = join(root, "ticker-runtime.json");
    try {
      await writeFile(runtimePath, JSON.stringify(validRuntime()), "utf-8");
      const { LocalFileTickerRuntimeRepository } = await import("./ticker-runtime-repository");
      const repository = new LocalFileTickerRuntimeRepository(runtimePath);

      await expect(repository.batchAfter(2)).resolves.toBeUndefined();
      await expect(repository.batchAfter(1)).resolves.toEqual({
        schemaVersion: 1,
        sequence: 2,
        asOf: 2_000,
        full: false,
        updates: [["BTCUSDT", 102, 200]]
      });
      await expect(repository.batchAfter(0)).resolves.toEqual({
        schemaVersion: 1,
        sequence: 2,
        asOf: 2_000,
        full: true,
        updates: [
          ["BTCUSDT", 102, 200],
          ["ETHUSDT", 51, 200]
        ]
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("fails closed for malformed or structurally invalid runtime payloads", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-runtime-"));
    const runtimePath = join(root, "ticker-runtime.json");
    try {
      const { LocalFileTickerRuntimeRepository } = await import("./ticker-runtime-repository");
      const repository = new LocalFileTickerRuntimeRepository(runtimePath);
      await writeFile(runtimePath, "{partial", "utf-8");
      await expect(repository.batchAfter(0)).rejects.toThrow("invalid ticker runtime");

      await writeFile(
        runtimePath,
        JSON.stringify({ ...validRuntime(), fullUpdates: [["BTCUSDT", -1, 200]] }),
        "utf-8"
      );
      await expect(repository.batchAfter(0)).rejects.toThrow("invalid ticker runtime");

      await writeFile(
        runtimePath,
        JSON.stringify({
          ...validRuntime(),
          fullUpdates: [
            ["BTCUSDT", 102, 200],
            ["BTCUSDT", 103, 201]
          ]
        }),
        "utf-8"
      );
      await expect(repository.batchAfter(0)).rejects.toThrow("invalid ticker runtime");

      await writeFile(
        runtimePath,
        JSON.stringify({ ...validRuntime(), schemaVersion: 2 }),
        "utf-8"
      );
      await expect(repository.batchAfter(0)).rejects.toThrow("invalid ticker runtime");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("reuses unchanged parsed state and invalidates the cache after replacement", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-cache-"));
    const runtimePath = join(root, "ticker-runtime.json");
    try {
      await writeFile(runtimePath, JSON.stringify(validRuntime()), "utf-8");
      const { LocalFileTickerRuntimeRepository } = await import("./ticker-runtime-repository");
      const first = await new LocalFileTickerRuntimeRepository(runtimePath).batchAfter(0);
      const second = await new LocalFileTickerRuntimeRepository(runtimePath).batchAfter(0);

      expect(second?.updates).toBe(first?.updates);

      await writeFile(
        runtimePath,
        JSON.stringify({
          ...validRuntime(),
          sequence: 3,
          fullUpdates: [["BTCUSDT", 103, 300]],
          deltaUpdates: [["BTCUSDT", 103, 300]]
        }),
        "utf-8"
      );
      const changedAt = new Date(Date.now() + 1_000);
      await utimes(runtimePath, changedAt, changedAt);
      const changed = await new LocalFileTickerRuntimeRepository(runtimePath).batchAfter(0);

      expect(changed?.updates).not.toBe(first?.updates);
      expect(changed).toMatchObject({ sequence: 3, updates: [["BTCUSDT", 103, 300]] });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

function validRuntime() {
  return {
    schemaVersion: 1,
    sequence: 2,
    asOf: 2_000,
    fullUpdates: [
      ["BTCUSDT", 102, 200],
      ["ETHUSDT", 51, 200]
    ],
    deltaUpdates: [["BTCUSDT", 102, 200]]
  };
}
