import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { writeJsonFileAtomic } from "$lib/server/atomic-json-store";
import { withLockFile } from "$lib/server/lock-file-guard";
import {
  cloneDashboardViewSettings,
  defaultDashboardViewSettings,
  normalizeDashboardViewSettings,
  type DashboardViewSettings
} from "$lib/market/dashboard-filters";
import { resolveStatePaths } from "$lib/server/state-paths";

export class LocalFileDashboardViewSettingsRepository {
  constructor(private readonly rootDir = defaultDashboardViewSettingsDir()) {}

  async get() {
    try {
      return normalizeDashboardViewSettings(JSON.parse(await readFile(this.currentPath(), "utf-8")));
    } catch {
      return cloneDashboardViewSettings(defaultDashboardViewSettings);
    }
  }

  async save(settings: DashboardViewSettings) {
    const normalized = normalizeDashboardViewSettings(settings);
    const currentPath = this.currentPath();
    await withLockFile(`${currentPath}.lock`, () => writeJsonFileAtomic(currentPath, normalized));
    return normalized;
  }

  private currentPath() {
    return resolve(this.rootDir, "current.json");
  }
}

export function createDashboardViewSettingsRepository() {
  return new LocalFileDashboardViewSettingsRepository();
}

function defaultDashboardViewSettingsDir() {
  return resolveStatePaths().dashboardViewSettingsDir;
}
