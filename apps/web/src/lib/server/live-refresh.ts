import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { createSnapshotRepository, type SnapshotRepository } from "$lib/server/snapshot-repository";
import type { PrepWatchdeckScannerSnapshot } from "$lib/generated/scanner-snapshot";

type ExecFileResult = {
  stdout: string;
  stderr: string;
};

export type LiveRefreshFallback = {
  reason: "DUCKDB_LOCK";
  message: string;
};

export type LiveRefreshResult = {
  snapshot: PrepWatchdeckScannerSnapshot;
  fallback?: LiveRefreshFallback;
};

let refreshInFlight: Promise<LiveRefreshResult> | null = null;

type LiveRefreshDependencies = {
  execFile?: typeof execFileAsync;
  repository?: SnapshotRepository;
  scannerCoreDir?: string;
  env?: NodeJS.ProcessEnv;
};

function execFileAsync(
  file: string,
  args: string[],
  options: { cwd: string; env: NodeJS.ProcessEnv; timeout: number }
) {
  return new Promise<ExecFileResult>((resolvePromise, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(commandFailureMessage(error, stdout, stderr)));
        return;
      }
      resolvePromise({ stdout, stderr });
    });
  });
}

export function commandFailureMessage(error: Error, stdout: string, stderr: string) {
  return stderr.trim() || stdout.trim() || error.message;
}

export async function refreshLiveSnapshot(dependencies: LiveRefreshDependencies = {}) {
  return (await refreshLiveSnapshotWithResult(dependencies)).snapshot;
}

export async function refreshLiveSnapshotWithResult(dependencies: LiveRefreshDependencies = {}) {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = runLiveRefresh(dependencies);
  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
}

async function runLiveRefresh(dependencies: LiveRefreshDependencies) {
  const scannerCoreDir = dependencies.scannerCoreDir ?? resolve(process.cwd(), "../scanner-core");
  const env = dependencies.env ?? process.env;
  const template = env.PREP_WATCHDECK_LIVE_TEMPLATE ?? env.TEMPLATE ?? "balanced";
  const exec = dependencies.execFile ?? execFileAsync;
  const repository = dependencies.repository ?? createSnapshotRepository();
  let fallback: LiveRefreshFallback | undefined;

  try {
    await exec("uv", ["run", "watchdeck", "publish-service", "--template", template], {
      cwd: scannerCoreDir,
      env,
      timeout: 120_000
    });
  } catch (cause) {
    if (!isDuckDbLockError(cause)) {
      throw cause;
    }
    fallback = {
      reason: "DUCKDB_LOCK",
      message: "service store is locked; reloaded the existing latest snapshot"
    };
  }

  return {
    snapshot: await repository.latest(),
    fallback
  };
}

export function isDuckDbLockError(cause: unknown) {
  const message = cause instanceof Error ? cause.message : String(cause);
  const lower = message.toLowerCase();
  const mentionsDuckDb = lower.includes("duckdb") || lower.includes("watchdeck.duckdb");
  const mentionsLock =
    lower.includes("could not set lock on file") ||
    lower.includes("conflicting lock") ||
    lower.includes("duckdb cache is locked") ||
    lower.includes("cache locked");
  return mentionsDuckDb && mentionsLock;
}
