import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LocalFileServiceStateRepository } from "./service-state-repository";

describe("LocalFileServiceStateRepository", () => {
  it("loads service-state.json and returns a derived view", async () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-service-state-"));
    const serviceStatePath = join(root, "service-state.json");
    try {
      writeFileSync(
        serviceStatePath,
        JSON.stringify({
          schemaVersion: 1,
          generatedAtMs: Date.now(),
          dataAsOfMs: Date.now(),
          productType: "USDT-FUTURES",
          streamSymbols: 666,
          streamShards: 28
        }) + "\n",
        "utf-8"
      );

      const state = await new LocalFileServiceStateRepository(serviceStatePath).latest();

      expect(state?.raw.productType).toBe("USDT-FUTURES");
      expect(state?.view.streamSymbols).toBe(666);
      expect(state?.view.streamShards).toBe(28);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns undefined when service-state.json is missing", async () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-service-state-missing-"));
    try {
      await expect(
        new LocalFileServiceStateRepository(join(root, "missing.json")).latest()
      ).resolves.toBeUndefined();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns an unreadable state when service-state.json is broken", async () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-service-state-broken-"));
    const serviceStatePath = join(root, "service-state.json");
    try {
      writeFileSync(serviceStatePath, "{not-json", "utf-8");

      const state = await new LocalFileServiceStateRepository(serviceStatePath).latest();

      expect(state?.view).toMatchObject({
        status: "unreadable",
        label: "Service 状態エラー"
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
