import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GET } from "./+server";
import type { RequestEvent } from "./$types";

describe("symbol chart API", () => {
  it("returns an empty chart payload instead of 404 when chart file is missing", async () => {
    const previousChartsDir = process.env.SCANNER_CHARTS_DIR;
    const chartsDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-empty-charts-"));
    process.env.SCANNER_CHARTS_DIR = chartsDir;
    try {
      const event = {
        params: { symbol: "VELVETUSDT" },
        url: new URL("http://localhost/api/symbols/VELVETUSDT/chart?tf=15m&runId=run-1")
      } as RequestEvent;
      const response = await GET(event);
      const payload = await response.json();

      expect(response.status).toBe(200);
      expect(payload).toMatchObject({
        schemaVersion: 2,
        snapshotRunId: "run-1",
        symbol: "VELVETUSDT",
        timeframes: {
          "15m": []
        }
      });
    } finally {
      if (previousChartsDir === undefined) {
        delete process.env.SCANNER_CHARTS_DIR;
      } else {
        process.env.SCANNER_CHARTS_DIR = previousChartsDir;
      }
      rmSync(chartsDir, { recursive: true, force: true });
    }
  });

  it("rejects invalid timeframe and missing runId as bad requests", async () => {
    await expect(
      GET(
        event(
          "ALTUSDT",
          "http://localhost/api/symbols/ALTUSDT/chart?tf=74h&runId=run-1"
        )
      )
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      GET(event("ALTUSDT", "http://localhost/api/symbols/ALTUSDT/chart?tf=15m"))
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      GET(
        event(
          "../ALTUSDT",
          "http://localhost/api/symbols/..%2FALTUSDT/chart?tf=15m&runId=run-1"
        )
      )
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      GET(
        event(
          "ALTUSDT",
          "http://localhost/api/symbols/ALTUSDT/chart?tf=15m&runId=%20%20"
        )
      )
    ).rejects.toMatchObject({ status: 400 });
  });

  it("keeps the default 15m empty-chart compatibility response", async () => {
    const previousChartsDir = process.env.SCANNER_CHARTS_DIR;
    const chartsDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-default-chart-"));
    process.env.SCANNER_CHARTS_DIR = chartsDir;
    try {
      const response = await GET(
        event("ALTUSDT", "http://localhost/api/symbols/ALTUSDT/chart?runId=run-1")
      );

      expect(response.status).toBe(200);
      await expect(response.json()).resolves.toMatchObject({
        schemaVersion: 2,
        snapshotRunId: "run-1",
        timeframes: { "15m": [] }
      });
    } finally {
      if (previousChartsDir === undefined) {
        delete process.env.SCANNER_CHARTS_DIR;
      } else {
        process.env.SCANNER_CHARTS_DIR = previousChartsDir;
      }
      rmSync(chartsDir, { recursive: true, force: true });
    }
  });

  it("rejects invalid schema and a chart from a different snapshot run", async () => {
    const previousChartsDir = process.env.SCANNER_CHARTS_DIR;
    const chartsDir = mkdtempSync(join(tmpdir(), "prep-watchdeck-invalid-charts-"));
    process.env.SCANNER_CHARTS_DIR = chartsDir;
    try {
      const chartPath = join(chartsDir, "ALTUSDT.json");
      writeFileSync(
        chartPath,
        JSON.stringify({
          schemaVersion: 1,
          symbol: "ALTUSDT",
          generatedAt: 1,
          dataAsOf: 1,
          timeframes: { "15m": [] }
        }),
        "utf-8"
      );
      await expect(
        GET(
          event(
            "ALTUSDT",
            "http://localhost/api/symbols/ALTUSDT/chart?tf=15m&runId=run-new"
          )
        )
      ).rejects.toMatchObject({ status: 503 });

      writeFileSync(
        chartPath,
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
      await expect(
        GET(
          event(
            "ALTUSDT",
            "http://localhost/api/symbols/ALTUSDT/chart?tf=15m&runId=run-new"
          )
        )
      ).rejects.toMatchObject({ status: 409 });
    } finally {
      if (previousChartsDir === undefined) {
        delete process.env.SCANNER_CHARTS_DIR;
      } else {
        process.env.SCANNER_CHARTS_DIR = previousChartsDir;
      }
      rmSync(chartsDir, { recursive: true, force: true });
    }
  });
});

function event(symbol: string, url: string) {
  return { params: { symbol }, url: new URL(url) } as RequestEvent;
}
