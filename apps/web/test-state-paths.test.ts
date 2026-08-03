import { describe, expect, test } from "bun:test";
import { resolve } from "node:path";
import {
  resolveWebTestStatePaths,
  shellEnvironment
} from "./test-state-paths";

describe("Web test state paths", () => {
  test("keeps the compatibility fallback under repo var/tmp", () => {
    const paths = resolveWebTestStatePaths("e2e", {}, "/repo/apps/web");

    expect(paths.stateDir).toBe("/repo/var");
    expect(paths.runtimeRoot).toBe("/repo/var/tmp/e2e/runtime");
    expect(paths.snapshotPath).toBe("/repo/var/tmp/e2e/runtime/snapshots/latest.json");
    expect(paths.playwrightOutputDir).toBe("/repo/var/tmp/e2e/playwright-results");
    expect("tradeMemosDir" in paths).toBe(false);
    expect("attackTicketsDir" in paths).toBe(false);
  });

  test("derives isolated gate roots from PREP_WATCHDECK_STATE_DIR", () => {
    const paths = resolveWebTestStatePaths(
      "performance",
      { PREP_WATCHDECK_STATE_DIR: "/external/state" },
      "/repo/apps/web"
    );

    expect(paths.runtimeRoot).toBe("/external/state/tmp/performance/runtime");
    expect(paths.cacheDbPath).toBe(
      "/external/state/tmp/performance/runtime/watchdeck.duckdb"
    );
    expect(paths.chartsDir).toBe(
      "/external/state/tmp/performance/runtime/snapshots/charts/latest"
    );
  });

  test("quotes shell environment values without splitting spaces or apostrophes", () => {
    expect(shellEnvironment({ PATH_VALUE: "/tmp/space and'quote" })).toBe(
      `PATH_VALUE='/tmp/space and'\"'\"'quote'`
    );
  });

  test("normalizes relative state roots from the Web working directory", () => {
    const paths = resolveWebTestStatePaths(
      "soak",
      { PREP_WATCHDECK_STATE_DIR: "custom-state" },
      "/repo/apps/web"
    );

    expect(paths.stateDir).toBe(resolve("/repo", "custom-state"));
  });

  test("fails closed when a retired record directory override is configured", () => {
    for (const name of [
      "PREP_WATCHDECK_TRADE_MEMOS_DIR",
      "TRADE_MEMOS_DIR",
      "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
      "ATTACK_TICKETS_DIR"
    ]) {
      for (const value of ["", "/retired-records"]) {
        expect(() =>
          resolveWebTestStatePaths("e2e", { [name]: value }, "/repo/apps/web")
        ).toThrow(`retired record state override is no longer supported: ${name}`);
      }
    }
  });
});
