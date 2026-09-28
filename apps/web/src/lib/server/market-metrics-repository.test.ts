import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";
import { readMarketMetrics } from "./market-metrics-repository";

test("valid old metrics keep their source timestamp; malformed metrics fail independently", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-metrics-"));
  const path = join(root, "market-metrics.json");
  try {
    const payload = {
      schemaVersion: 1, metricVersion: "native-endpoints-v1",
      generationId: "fixture-1", generatedAt: "2020-01-01T00:00:00Z",
      candleCutoff: "2020-01-01T00:00:00Z",
      timingPolicy: { candleLagSeconds: 180, candleMaxAgeSeconds: 300 },
      rows: []
    };
    await writeFile(path, JSON.stringify(payload));
    expect((await readMarketMetrics(path)).generatedAt).toBe(payload.generatedAt);
    await writeFile(path, JSON.stringify({ ...payload, rows: "invalid" }));
    await expect(readMarketMetrics(path)).rejects.toThrow("market metrics invalid");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
