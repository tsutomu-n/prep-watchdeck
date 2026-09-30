import { homedir } from "node:os";
import { resolve } from "node:path";

type Environment = Record<string, string | undefined>;

export type MarketStatePaths = {
  stateDir: string;
  artifactDir: string;
  universeSnapshotPath: string;
  marketChartPath: string;
  selectedMarketPath: string;
  serviceStatePath: string;
  selectionCommandPath: string;
  pastNotesDir: string;
  userWorkspacePath: string;
  marketMetricsPath: string;
  candleRecoveryStatePath: string;
  candleAuditIndexPath: string;
  candleAuditRunsDir: string;
};

export function resolveMarketStatePaths(env: Environment = process.env): MarketStatePaths {
  const stateDir = resolve(
    env.PREP_WATCHDECK_MARKET_STATE_DIR ??
      resolve(homedir(), ".local", "share", "prep-watchdeck-market")
  );
  const artifactDir = resolve(stateDir, "artifacts");

  return {
    stateDir,
    artifactDir,
    universeSnapshotPath: resolve(artifactDir, "universe-snapshot.json"),
    marketChartPath: resolve(artifactDir, "market-chart.json"),
    selectedMarketPath: resolve(artifactDir, "selected-market.json"),
    serviceStatePath: resolve(artifactDir, "service-state.json"),
    selectionCommandPath: resolve(stateDir, "control", "selection.json"),
    pastNotesDir: resolve(stateDir, "past-notes"),
    userWorkspacePath: resolve(stateDir, "user-workspace.json"),
    marketMetricsPath: resolve(artifactDir, "market-metrics.json"),
    candleRecoveryStatePath: resolve(artifactDir, "candle-recovery-state.json"),
    candleAuditIndexPath: resolve(artifactDir, "candle-audit-index.json"),
    candleAuditRunsDir: resolve(stateDir, "candle-audits", "runs")
  };
}
