import { mkdtemp, readFile, rm, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { defaultDashboardViewSettings } from "$lib/market/dashboard-filters";
import { LocalFileDashboardViewSettingsRepository } from "./dashboard-view-settings-repository";

describe("LocalFileDashboardViewSettingsRepository", () => {
  it("treats missing and malformed files as default settings", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-settings-"));
    try {
      const repo = new LocalFileDashboardViewSettingsRepository(root);
      await expect(repo.get()).resolves.toMatchObject({
        schemaVersion: 1,
        views: { surge: { thresholdPctByTimeframe: { "15m": 2 } } }
      });
      await writeFile(join(root, "current.json"), "{ invalid json", "utf-8");
      await expect(repo.get()).resolves.toMatchObject({
        views: { watch: { categories: ["WATCH"] } }
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("normalizes partial file data with defaults", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-settings-"));
    try {
      await writeFile(
        join(root, "current.json"),
        JSON.stringify({
          schemaVersion: 1,
          updatedAt: "2026-06-29T00:00:00.000Z",
          views: {
            turnover: {
              kind: "turnoverAtLeast",
              thresholdUsdtByTimeframe: { "15m": 123_456, "74h": 999_999 },
              excludedCategories: ["NO_TRADE"]
            }
          }
        }),
        "utf-8"
      );

      const settings = await new LocalFileDashboardViewSettingsRepository(root).get();
      expect(settings.views.turnover.thresholdUsdtByTimeframe["15m"]).toBe(123_456);
      expect(settings.views.turnover.thresholdUsdtByTimeframe["5m"]).toBe(10_000);
      expect("74h" in settings.views.turnover.thresholdUsdtByTimeframe).toBe(false);
      expect(settings.views.watch.categories).toEqual(["WATCH"]);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("saves the current settings file with the normalized schema shape", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-settings-"));
    try {
      const repo = new LocalFileDashboardViewSettingsRepository(root);
      await repo.save({
        ...defaultDashboardViewSettings,
        updatedAt: "2026-06-29T00:00:00.000Z",
        views: {
          ...defaultDashboardViewSettings.views,
          surge: {
            kind: "changePctAtLeast",
            thresholdPctByTimeframe: { "5m": 7, "15m": 7, "1h": 7, "4h": 7, "24h": 7 },
            excludedCategories: ["NO_TRADE"]
          }
        }
      });

      const file = JSON.parse(await readFile(join(root, "current.json"), "utf-8"));
      expect(file).toMatchObject({
        schemaVersion: 1,
        updatedAt: "2026-06-29T00:00:00.000Z",
        views: {
          surge: {
            kind: "changePctAtLeast",
            thresholdPctByTimeframe: { "15m": 7 },
            excludedCategories: ["NO_TRADE"]
          }
        }
      });
      expect(await fileExists(join(root, "current.json.tmp"))).toBe(false);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("uses the shared lock path before saving current settings", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-settings-"));
    try {
      const lockPath = join(root, "current.json.lock");
      await writeFile(lockPath, "stale", "utf-8");
      await utimes(lockPath, new Date(0), new Date(0));

      const repo = new LocalFileDashboardViewSettingsRepository(root);
      await repo.save(defaultDashboardViewSettings);

      await expect(readFile(lockPath, "utf-8")).rejects.toMatchObject({ code: "ENOENT" });
      await expect(readFile(join(root, "current.json"), "utf-8")).resolves.toContain('"schemaVersion": 1');
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

async function fileExists(path: string) {
  try {
    await readFile(path, "utf-8");
    return true;
  } catch {
    return false;
  }
}
