import { mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LocalFileChartDataRepository } from "./chart-data-repository";

describe("LocalFileChartDataRepository", () => {
  it("loads chart data for a safe symbol and timeframe", async () => {
    const chartDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-chart-data-"));
    try {
      writeFileSync(
        join(chartDir, "ALTUSDT.json"),
        JSON.stringify({
          schemaVersion: 2,
          snapshotRunId: "run-1",
          symbol: "ALTUSDT",
          generatedAt: 1_781_000_000_000,
          dataAsOf: 1_781_000_000_000,
          timeframes: {
            "5m": [{ ts: 1_781_000_000_000, open: 1, high: 2, low: 0.5, close: 1.5, quoteVolume: 10 }],
            "15m": [{ ts: 1_781_000_000_000, open: 1, high: 3, low: 0.5, close: 2.5, quoteVolume: 30 }]
          }
        }) + "\n",
        "utf-8"
      );

      const payload = await new LocalFileChartDataRepository(chartDir).symbol(
        "ALTUSDT",
        "15m",
        "run-1"
      );

      expect(payload).toMatchObject({
        schemaVersion: 2,
        snapshotRunId: "run-1",
        symbol: "ALTUSDT",
        timeframes: {
          "15m": [{ close: 2.5, quoteVolume: 30 }]
        }
      });
    } finally {
      rmSync(chartDir, { recursive: true, force: true });
    }
  });

  it("rejects unsafe symbols before reading files", async () => {
    const repository = new LocalFileChartDataRepository("/tmp");

    await expect(repository.symbol("../ALTUSDT", "15m", "run-1")).rejects.toThrow(
      "invalid symbol"
    );
  });

  it("rejects legacy schema, run mismatch, and non-array timeframe bars", async () => {
    const chartDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-chart-data-invalid-"));
    const repository = new LocalFileChartDataRepository(chartDir);
    try {
      writeFileSync(
        join(chartDir, "ALTUSDT.json"),
        JSON.stringify({
          schemaVersion: 1,
          symbol: "ALTUSDT",
          generatedAt: 1,
          dataAsOf: 1,
          timeframes: { "15m": [] }
        }),
        "utf-8"
      );
      await expect(repository.symbol("ALTUSDT", "15m", "run-1")).rejects.toThrow(
        "invalid chart data"
      );

      writeFileSync(
        join(chartDir, "ALTUSDT.json"),
        JSON.stringify({
          schemaVersion: 2,
          snapshotRunId: "run-old",
          symbol: "ALTUSDT",
          generatedAt: 1,
          dataAsOf: 1,
          timeframes: { "15m": [] }
        }),
        "utf-8"
      );
      await expect(repository.symbol("ALTUSDT", "15m", "run-new")).rejects.toThrow(
        "snapshot run mismatch"
      );

      writeFileSync(
        join(chartDir, "ALTUSDT.json"),
        JSON.stringify({
          schemaVersion: 2,
          snapshotRunId: "run-1",
          symbol: "ALTUSDT",
          generatedAt: 1,
          dataAsOf: 1,
          timeframes: { "15m": {} }
        }),
        "utf-8"
      );
      await expect(repository.symbol("ALTUSDT", "15m", "run-1")).rejects.toThrow(
        "invalid chart data"
      );
    } finally {
      rmSync(chartDir, { recursive: true, force: true });
    }
  });

  it("reuses an unchanged parsed chart and invalidates the cache after replacement", async () => {
    const chartDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-chart-cache-"));
    const chartPath = join(chartDir, "ALTUSDT.json");
    try {
      writeFileSync(chartPath, JSON.stringify(chartPayload(1.5)), "utf-8");
      const first = await new LocalFileChartDataRepository(chartDir).symbol(
        "ALTUSDT",
        "15m",
        "run-1"
      );
      const second = await new LocalFileChartDataRepository(chartDir).symbol(
        "ALTUSDT",
        "15m",
        "run-1"
      );

      expect(second?.timeframes["15m"]).toBe(first?.timeframes["15m"]);

      writeFileSync(chartPath, JSON.stringify(chartPayload(2.5)), "utf-8");
      const changedAt = new Date(Date.now() + 1_000);
      utimesSync(chartPath, changedAt, changedAt);
      const changed = await new LocalFileChartDataRepository(chartDir).symbol(
        "ALTUSDT",
        "15m",
        "run-1"
      );

      expect(changed?.timeframes["15m"]).not.toBe(first?.timeframes["15m"]);
      expect(changed?.timeframes["15m"]?.[0].close).toBe(2.5);
    } finally {
      rmSync(chartDir, { recursive: true, force: true });
    }
  });
});

function chartPayload(close: number) {
  return {
    schemaVersion: 2,
    snapshotRunId: "run-1",
    symbol: "ALTUSDT",
    generatedAt: 1,
    dataAsOf: 1,
    timeframes: {
      "15m": [{ ts: 1, open: 1, high: 3, low: 0.5, close, quoteVolume: 30 }]
    }
  };
}
