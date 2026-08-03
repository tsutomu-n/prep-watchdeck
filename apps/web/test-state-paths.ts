import { resolve } from "node:path";

type TestKind = "e2e" | "performance" | "soak";
type Environment = Record<string, string | undefined>;

export type WebTestStatePaths = {
  stateDir: string;
  artifactRoot: string;
  runtimeRoot: string;
  playwrightOutputDir: string;
  snapshotDir: string;
  snapshotPath: string;
  serviceStatePath: string;
  chartsDir: string;
  tickerRuntimePath: string;
  cacheDbPath: string;
  pastNotesDir: string;
  dashboardViewSettingsDir: string;
};

export function resolveWebTestStatePaths(
  kind: TestKind,
  env: Environment = process.env,
  cwd = process.cwd()
): WebTestStatePaths {
  assertNoRetiredRecordOverrides(env);

  const repoRoot = resolve(cwd, "../..");
  const stateDir = resolve(repoRoot, env.PREP_WATCHDECK_STATE_DIR ?? "var");
  const artifactRoot = resolve(stateDir, "tmp", kind);
  const runtimeRoot = resolve(artifactRoot, "runtime");
  const snapshotDir = resolve(runtimeRoot, "snapshots");

  return {
    stateDir,
    artifactRoot,
    runtimeRoot,
    playwrightOutputDir: resolve(artifactRoot, "playwright-results"),
    snapshotDir,
    snapshotPath: resolve(snapshotDir, "latest.json"),
    serviceStatePath: resolve(snapshotDir, "service-state.json"),
    chartsDir: resolve(snapshotDir, "charts", "latest"),
    tickerRuntimePath: resolve(snapshotDir, "ticker-runtime.json"),
    cacheDbPath: resolve(runtimeRoot, "watchdeck.duckdb"),
    pastNotesDir: resolve(runtimeRoot, "past-notes"),
    dashboardViewSettingsDir: resolve(runtimeRoot, "dashboard-view-settings")
  };
}

function assertNoRetiredRecordOverrides(env: Environment) {
  for (const name of [
    "PREP_WATCHDECK_TRADE_MEMOS_DIR",
    "TRADE_MEMOS_DIR",
    "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
    "ATTACK_TICKETS_DIR"
  ]) {
    if (Object.prototype.hasOwnProperty.call(env, name)) {
      throw new Error(`retired record state override is no longer supported: ${name}`);
    }
  }
}

export function shellEnvironment(values: Record<string, string>) {
  return Object.entries(values)
    .map(([name, value]) => `${name}=${shellQuote(value)}`)
    .join(" ");
}

function shellQuote(value: string) {
  return `'${value.replaceAll("'", `'\"'\"'`)}'`;
}
