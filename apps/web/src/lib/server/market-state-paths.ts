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
    pastNotesDir: resolve(stateDir, "past-notes")
  };
}
