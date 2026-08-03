import { describe, expect, it } from "vitest";
import {
  commandFailureMessage,
  isDuckDbLockError,
  refreshLiveSnapshot,
  refreshLiveSnapshotWithResult
} from "./live-refresh";

describe("live refresh helpers", () => {
  it("detects DuckDB service writer lock errors", () => {
    expect(
      isDuckDbLockError(
        new Error(
          'IO Error: Could not set lock on file "/home/tn/projects/prep-watchdeck/var/watchdeck.duckdb": Conflicting lock is held'
        )
      )
    ).toBe(true);
  });

  it("detects scanner-core wrapped DuckDB cache lock errors", () => {
    expect(
      isDuckDbLockError(
        new Error(
          "cache locked DuckDB cache is locked by another watchdeck process: ../../var/watchdeck.duckdb. Wait for the running scan to finish"
        )
      )
    ).toBe(true);
  });

  it("does not classify unrelated command failures as lock fallback", () => {
    expect(isDuckDbLockError(new Error("template not found"))).toBe(false);
  });

  it("surfaces scanner stdout when a command failure has no stderr", () => {
    expect(
      commandFailureMessage(
        new Error("Command failed"),
        "service unavailable service candle data is unavailable\n",
        ""
      )
    ).toBe("service unavailable service candle data is unavailable");
    expect(commandFailureMessage(new Error("Command failed"), "stdout", "stderr")).toBe("stderr");
  });

  it("falls back to the existing latest snapshot only on DuckDB lock", async () => {
    const snapshot = { runId: "existing" };

    await expect(
      refreshLiveSnapshot({
        execFile: async () => {
          throw new Error(
            'IO Error: Could not set lock on file "/tmp/watchdeck.duckdb": Conflicting lock is held'
          );
        },
        repository: {
          latest: async () => snapshot as never,
          summary: async () => ({}),
          rankings: async () => [],
          symbols: async () => [],
          symbol: async () => undefined
        },
        scannerCoreDir: "/tmp/scanner-core",
        env: {}
      })
    ).resolves.toBe(snapshot);
  });

  it("returns fallback details when DuckDB lock keeps the existing latest snapshot", async () => {
    const snapshot = { runId: "existing" };

    await expect(
      refreshLiveSnapshotWithResult({
        execFile: async () => {
          throw new Error(
            'IO Error: Could not set lock on file "/tmp/watchdeck.duckdb": Conflicting lock is held'
          );
        },
        repository: {
          latest: async () => snapshot as never,
          summary: async () => ({}),
          rankings: async () => [],
          symbols: async () => [],
          symbol: async () => undefined
        },
        scannerCoreDir: "/tmp/scanner-core",
        env: {}
      })
    ).resolves.toMatchObject({
      snapshot,
      fallback: {
        reason: "DUCKDB_LOCK",
        message: "service store is locked; reloaded the existing latest snapshot"
      }
    });
  });

  it("does not hide non-lock publish failures", async () => {
    await expect(
      refreshLiveSnapshot({
        execFile: async () => {
          throw new Error("template not found");
        },
        repository: {
          latest: async () => ({}) as never,
          summary: async () => ({}),
          rankings: async () => [],
          symbols: async () => [],
          symbol: async () => undefined
        },
        scannerCoreDir: "/tmp/scanner-core",
        env: {}
      })
    ).rejects.toThrow("template not found");
  });

  it("does not fall back when service candle data is stale", async () => {
    await expect(
      refreshLiveSnapshot({
        execFile: async () => {
          throw new Error(
            "service unavailable service candle data is stale: lag=950000ms max=120000ms"
          );
        },
        repository: {
          latest: async () => ({ runId: "existing" }) as never,
          summary: async () => ({}),
          rankings: async () => [],
          symbols: async () => [],
          symbol: async () => undefined
        },
        scannerCoreDir: "/tmp/scanner-core",
        env: {}
      })
    ).rejects.toThrow("service candle data is stale");
  });
});
