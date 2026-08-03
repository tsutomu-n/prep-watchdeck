import { dirname, resolve } from "node:path";

type Environment = Record<string, string | undefined>;

export type StatePaths = {
  stateDir: string;
  databasePath: string;
  snapshotPath: string;
  serviceStatePath: string;
  tickerRuntimePath: string;
  chartDir: string;
  pastNotesDir: string;
  dashboardViewSettingsDir: string;
};

export function resolveStatePaths(
  env: Environment = process.env,
  cwd = process.cwd()
): StatePaths {
  assertNoRetiredRecordOverrides(env);

  const repoRoot = resolve(cwd, "../..");
  const scannerCwd = resolve(cwd, "../scanner-core");
  const stateDir = resolve(repoRoot, env.PREP_WATCHDECK_STATE_DIR ?? "var");
  const scannerSnapshotPath = env.PREP_WATCHDECK_OUT_DIR
    ? resolve(scannerCwd, env.PREP_WATCHDECK_OUT_DIR, "latest.json")
    : undefined;
  const webSnapshotPath = env.SCANNER_SNAPSHOT_PATH
    ? resolve(cwd, env.SCANNER_SNAPSHOT_PATH)
    : undefined;
  assertMatchingPaths(
    "scanner and Web snapshot paths",
    scannerSnapshotPath,
    webSnapshotPath
  );
  const snapshotPath =
    webSnapshotPath ??
    scannerSnapshotPath ??
    resolve(stateDir, "snapshots", "latest.json");
  const snapshotDir = dirname(snapshotPath);
  const scannerServiceStatePath = resolveOptional(
    scannerCwd,
    env.PREP_WATCHDECK_SERVICE_STATE_PATH
  );
  const webServiceStatePath = resolveOptional(cwd, env.SCANNER_SERVICE_STATE_PATH);
  assertMatchingPaths(
    "scanner and Web service-state paths",
    scannerServiceStatePath,
    webServiceStatePath
  );
  const scannerTickerRuntimePath = resolveOptional(
    scannerCwd,
    env.PREP_WATCHDECK_TICKER_RUNTIME_PATH
  );
  const webTickerRuntimePath = resolveOptional(cwd, env.SCANNER_TICKER_RUNTIME_PATH);
  assertMatchingPaths(
    "scanner and Web ticker-runtime paths",
    scannerTickerRuntimePath,
    webTickerRuntimePath
  );
  const producerChartDir = resolve(snapshotDir, "charts", "latest");
  const webChartDir = resolveOptional(cwd, env.SCANNER_CHARTS_DIR);

  return {
    stateDir,
    databasePath: resolve(
      scannerCwd,
      env.PREP_WATCHDECK_CACHE_DB_PATH ?? resolve(stateDir, "watchdeck.duckdb")
    ),
    snapshotPath,
    serviceStatePath:
      webServiceStatePath ??
      scannerServiceStatePath ??
      resolve(snapshotDir, "service-state.json"),
    tickerRuntimePath:
      webTickerRuntimePath ??
      scannerTickerRuntimePath ??
      resolve(snapshotDir, "ticker-runtime.json"),
    chartDir: webChartDir ?? producerChartDir,
    pastNotesDir: resolvePrefixedOrLegacy(
      scannerCwd,
      cwd,
      env.PREP_WATCHDECK_PAST_NOTES_DIR,
      env.PAST_NOTES_DIR,
      resolve(stateDir, "past-notes")
    ),
    dashboardViewSettingsDir: resolvePrefixedOrLegacy(
      scannerCwd,
      cwd,
      env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR,
      undefined,
      resolve(stateDir, "dashboard-view-settings")
    )
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

function resolveOptional(base: string, value: string | undefined) {
  return value === undefined ? undefined : resolve(base, value);
}

function resolvePrefixedOrLegacy(
  scannerCwd: string,
  webCwd: string,
  prefixed: string | undefined,
  legacy: string | undefined,
  fallback: string
) {
  if (prefixed !== undefined) return resolve(scannerCwd, prefixed);
  if (legacy !== undefined) return resolve(webCwd, legacy);
  return fallback;
}

function assertMatchingPaths(
  label: string,
  scannerPath: string | undefined,
  webPath: string | undefined
) {
  if (
    scannerPath !== undefined &&
    webPath !== undefined &&
    scannerPath !== webPath
  ) {
    throw new Error(`${label} disagree: ${scannerPath} != ${webPath}`);
  }
}
