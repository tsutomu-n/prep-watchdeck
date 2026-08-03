import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { GET, PATCH } from "./+server";

const originalSettingsDir = process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR;

afterEach(() => {
  if (originalSettingsDir === undefined) {
    delete process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR;
  } else {
    process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR = originalSettingsDir;
  }
});

describe("/api/dashboard-view-settings", () => {
  it("returns current settings with defaults", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-route-"));
    process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR = root;
    try {
      const response = await GET();
      await expect(response.json()).resolves.toMatchObject({
        settings: {
          schemaVersion: 1,
          views: { surge: { thresholdPctByTimeframe: { "15m": 2 } } }
        },
        defaults: {
          schemaVersion: 1,
          views: { watch: { categories: ["WATCH"] } }
        }
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("updates a single view and resets it without changing all settings", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-route-"));
    process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR = root;
    try {
      const updated = await PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "surge",
          view: {
            kind: "changePctAtLeast",
            thresholdPctByTimeframe: { "5m": 5, "15m": 5, "1h": 5, "4h": 5, "24h": 5, "74h": 5 },
            excludedCategories: ["NO_TRADE"]
          }
        })
      );
      expect(updated.status).toBe(200);
      await expect(updated.json()).resolves.toMatchObject({
        ok: true,
        settings: { views: { surge: { thresholdPctByTimeframe: { "15m": 5 } } } }
      });

      const reset = await PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "reset-view",
          viewId: "surge"
        })
      );
      await expect(reset.json()).resolves.toMatchObject({
        ok: true,
        settings: { views: { surge: { thresholdPctByTimeframe: { "15m": 2 } } } }
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("resets all settings", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-view-route-"));
    process.env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR = root;
    try {
      await PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "watch",
          view: { kind: "categoryIn", categories: ["WATCH", "CAUTION"] }
        })
      );
      const reset = await PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "reset-all"
        })
      );
      await expect(reset.json()).resolves.toMatchObject({
        ok: true,
        settings: { views: { watch: { categories: ["WATCH"] } } }
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects invalid view settings payloads", async () => {
    await expect(
      PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "standard",
          view: { kind: "categoryIn", categories: ["WATCH"] }
        })
      )
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "surge",
          view: {
            kind: "changePctAtLeast",
            thresholdPctByTimeframe: { "5m": 1, "15m": 1, "1h": 1, "4h": 1, "24h": 1, "74h": 1, BAD: 1 },
            excludedCategories: ["NO_TRADE"]
          }
        })
      )
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "turnover",
          view: {
            kind: "turnoverAtLeast",
            thresholdUsdtByTimeframe: { "5m": -1, "15m": 1, "1h": 1, "4h": 1, "24h": 1, "74h": 1 },
            excludedCategories: ["NO_TRADE"]
          }
        })
      )
    ).rejects.toMatchObject({ status: 400 });
    await expect(
      PATCH(
        event("http://localhost/api/dashboard-view-settings", {
          action: "update-view",
          viewId: "quality",
          view: {
            kind: "dataQualityIn",
            allowedDataQualities: [],
            excludedCategories: ["NO_TRADE"]
          }
        })
      )
    ).rejects.toMatchObject({ status: 400 });
  });

  it("forbids non-localhost writes", async () => {
    await expect(
      PATCH(
        event("https://example.com/api/dashboard-view-settings", {
          action: "reset-all"
        })
      )
    ).rejects.toMatchObject({ status: 403 });
  });
});

function event(url: string, payload: unknown) {
  return {
    url: new URL(url),
    request: new Request(url, {
      method: "PATCH",
      body: JSON.stringify(payload),
      headers: { "content-type": "application/json" }
    })
  } as never;
}
