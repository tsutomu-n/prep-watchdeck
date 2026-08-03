import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveStatePaths } from "./state-paths";

const cwd = "/workspace/prep-watchdeck/apps/web";

describe("resolveStatePaths", () => {
  it("keeps the existing repo var defaults when no state dir is configured", () => {
    const paths = resolveStatePaths({}, cwd);
    const stateDir = resolve(cwd, "../../var");

    expect(paths).toEqual({
      stateDir,
      databasePath: resolve(stateDir, "watchdeck.duckdb"),
      snapshotPath: resolve(stateDir, "snapshots/latest.json"),
      serviceStatePath: resolve(stateDir, "snapshots/service-state.json"),
      tickerRuntimePath: resolve(stateDir, "snapshots/ticker-runtime.json"),
      chartDir: resolve(stateDir, "snapshots/charts/latest"),
      pastNotesDir: resolve(stateDir, "past-notes"),
      dashboardViewSettingsDir: resolve(stateDir, "dashboard-view-settings")
    });
  });

  it("derives every default path from PREP_WATCHDECK_STATE_DIR", () => {
    const stateDir = "/home/user/.local/share/prep-watchdeck";
    const paths = resolveStatePaths({ PREP_WATCHDECK_STATE_DIR: stateDir }, cwd);

    expect(paths.stateDir).toBe(stateDir);
    expect(paths.databasePath).toBe(resolve(stateDir, "watchdeck.duckdb"));
    expect(paths.snapshotPath).toBe(resolve(stateDir, "snapshots/latest.json"));
    expect(paths.serviceStatePath).toBe(resolve(stateDir, "snapshots/service-state.json"));
    expect(paths.tickerRuntimePath).toBe(resolve(stateDir, "snapshots/ticker-runtime.json"));
    expect(paths.chartDir).toBe(resolve(stateDir, "snapshots/charts/latest"));
    expect(paths.pastNotesDir).toBe(resolve(stateDir, "past-notes"));
    expect(paths.dashboardViewSettingsDir).toBe(resolve(stateDir, "dashboard-view-settings"));
  });

  it("resolves a relative state root from the repository root", () => {
    const paths = resolveStatePaths(
      { PREP_WATCHDECK_STATE_DIR: "custom-state" },
      cwd
    );

    expect(paths.stateDir).toBe("/workspace/prep-watchdeck/custom-state");
    expect(paths.snapshotPath).toBe(
      "/workspace/prep-watchdeck/custom-state/snapshots/latest.json"
    );
  });

  it("preserves snapshot override compatibility for adjacent runtime files", () => {
    const stateDir = "/state";
    const snapshotPath = "/custom/snapshots/latest.json";
    const paths = resolveStatePaths(
      {
        PREP_WATCHDECK_STATE_DIR: stateDir,
        SCANNER_SNAPSHOT_PATH: snapshotPath
      },
      cwd
    );

    expect(paths.snapshotPath).toBe(snapshotPath);
    expect(paths.serviceStatePath).toBe("/custom/snapshots/service-state.json");
    expect(paths.tickerRuntimePath).toBe("/custom/snapshots/ticker-runtime.json");
    expect(paths.chartDir).toBe("/custom/snapshots/charts/latest");
    expect(paths.pastNotesDir).toBe("/state/past-notes");
  });

  it("gives explicit individual overrides highest priority", () => {
    const paths = resolveStatePaths(
      {
        PREP_WATCHDECK_STATE_DIR: "/state",
        PREP_WATCHDECK_CACHE_DB_PATH: "/override/cache.duckdb",
        PREP_WATCHDECK_OUT_DIR: "/override/snapshots",
        SCANNER_SNAPSHOT_PATH: "/override/snapshots/latest.json",
        PREP_WATCHDECK_SERVICE_STATE_PATH: "/override/service.json",
        SCANNER_SERVICE_STATE_PATH: "/override/service.json",
        PREP_WATCHDECK_TICKER_RUNTIME_PATH: "/override/ticker.json",
        SCANNER_TICKER_RUNTIME_PATH: "/override/ticker.json",
        SCANNER_CHARTS_DIR: "/override/snapshots/charts/latest",
        PREP_WATCHDECK_PAST_NOTES_DIR: "/override/past",
        PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR: "/override/settings"
      },
      cwd
    );

    expect(paths).toEqual({
      stateDir: "/state",
      databasePath: "/override/cache.duckdb",
      snapshotPath: "/override/snapshots/latest.json",
      serviceStatePath: "/override/service.json",
      tickerRuntimePath: "/override/ticker.json",
      chartDir: "/override/snapshots/charts/latest",
      pastNotesDir: "/override/past",
      dashboardViewSettingsDir: "/override/settings"
    });
  });

  it("keeps the unprefixed Past Note directory override", () => {
    const paths = resolveStatePaths(
      {
        PREP_WATCHDECK_STATE_DIR: "/state",
        PAST_NOTES_DIR: "/legacy/past"
      },
      cwd
    );

    expect(paths.pastNotesDir).toBe("/legacy/past");
  });

  it("fails closed when a retired record directory override is configured", () => {
    for (const name of [
      "PREP_WATCHDECK_TRADE_MEMOS_DIR",
      "TRADE_MEMOS_DIR",
      "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
      "ATTACK_TICKETS_DIR"
    ]) {
      for (const value of ["", "/retired-records"]) {
        expect(() => resolveStatePaths({ [name]: value }, cwd)).toThrow(
          `retired record state override is no longer supported: ${name}`
        );
      }
    }
  });

  it("bridges scanner-core path overrides for direct Web startup", () => {
    const scannerCwd = resolve(cwd, "../scanner-core");
    const paths = resolveStatePaths(
      {
        PREP_WATCHDECK_OUT_DIR: "../../custom-snapshots",
        PREP_WATCHDECK_CACHE_DB_PATH: "../../custom.duckdb",
        PREP_WATCHDECK_SERVICE_STATE_PATH: "../../custom-snapshots/service.json",
        PREP_WATCHDECK_TICKER_RUNTIME_PATH: "../../custom-snapshots/ticker.json",
        PREP_WATCHDECK_PAST_NOTES_DIR: "../../custom-past",
        PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR: "../../custom-settings"
      },
      cwd
    );

    expect(paths.databasePath).toBe(resolve(scannerCwd, "../../custom.duckdb"));
    expect(paths.snapshotPath).toBe(
      resolve(scannerCwd, "../../custom-snapshots/latest.json")
    );
    expect(paths.serviceStatePath).toBe(
      resolve(scannerCwd, "../../custom-snapshots/service.json")
    );
    expect(paths.tickerRuntimePath).toBe(
      resolve(scannerCwd, "../../custom-snapshots/ticker.json")
    );
    expect(paths.chartDir).toBe(
      resolve(scannerCwd, "../../custom-snapshots/charts/latest")
    );
    expect(paths.pastNotesDir).toBe(resolve(scannerCwd, "../../custom-past"));
    expect(paths.dashboardViewSettingsDir).toBe(
      resolve(scannerCwd, "../../custom-settings")
    );
  });

  it("fails closed when scanner-core and Web overrides disagree", () => {
    expect(() =>
      resolveStatePaths(
        {
          PREP_WATCHDECK_OUT_DIR: "/scanner/snapshots",
          SCANNER_SNAPSHOT_PATH: "/web/snapshots/latest.json"
        },
        cwd
      )
    ).toThrow("scanner and Web snapshot paths disagree");

    expect(() =>
      resolveStatePaths(
        {
          PREP_WATCHDECK_SERVICE_STATE_PATH: "/scanner/service.json",
          SCANNER_SERVICE_STATE_PATH: "/web/service.json"
        },
        cwd
      )
    ).toThrow("scanner and Web service-state paths disagree");
  });
});
