import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmodSync,
  copyFileSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const createdRoots = [];
const archiveScript = resolve(
  import.meta.dirname,
  "archive-repo-history.sh"
);
const verifyArchiveScript = resolve(
  import.meta.dirname,
  "verify-repo-history-archive.sh"
);
const statePathScript = resolve(import.meta.dirname, "../lib/resolve-state-paths.sh");
const dailySummaryScript = resolve(import.meta.dirname, "../ops/watchdeck-daily-summary.mjs");
const finalizeReorganizationScript = resolve(
  import.meta.dirname,
  "finalize-reorganization.sh"
);
const migrateStateScript = resolve(import.meta.dirname, "migrate-state-dir.sh");
const verifyStateScript = resolve(import.meta.dirname, "verify-state-dir.sh");

afterEach(() => {
  for (const root of createdRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("repository history archive", () => {
  test("copies only non-current tracked docs and mockups with verified relative hashes", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-target-");

    runArchive(repo, archive);

    expect(existsSync(join(archive, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(archive, "docs", "archive", "older.md"))).toBe(true);
    expect(existsSync(join(archive, "mockups", "concept", "index.html"))).toBe(true);
    expect(existsSync(join(archive, "docs", "README.md"))).toBe(false);
    expect(existsSync(join(archive, "docs", "current", "overview.md"))).toBe(false);
    expect(existsSync(join(archive, "docs", "decisions", "0001-local.md"))).toBe(false);
    expect(existsSync(join(archive, "docs", "plans", "active", "current-plan.md"))).toBe(false);

    const manifest = readFileSync(join(archive, "MANIFEST.txt"), "utf-8")
      .trim()
      .split("\n");
    expect(manifest).toEqual([
      "docs/archive/older.md",
      "docs/old-guide.md",
      "mockups/concept/index.html"
    ]);
    expect(readFileSync(join(archive, "VERIFIED"), "utf-8")).toContain(
      "source files remain in place"
    );

    expect(existsSync(join(repo, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(repo, "mockups", "concept", "index.html"))).toBe(true);
  });

  test("refuses archive targets inside the repository", () => {
    const repo = createFixtureRepo();
    const result = spawnSync(
      "bash",
      [archiveScript, "--repo-root", repo, "--archive-dir", join(repo, "local-archive")],
      { encoding: "utf-8" }
    );

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("archive directory must be outside the repository");
  });

  test("refuses a non-empty target instead of overwriting existing evidence", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-existing-");
    writeFileSync(join(archive, "existing.txt"), "do not overwrite\n");

    const result = spawnSync(
      "bash",
      [archiveScript, "--repo-root", repo, "--archive-dir", archive],
      { encoding: "utf-8" }
    );

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("archive directory must not already contain files");
    expect(readFileSync(join(archive, "existing.txt"), "utf-8")).toBe("do not overwrite\n");
  });

  test("re-verifies the tracked manifest and both copies before source removal", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-verify-");
    runArchive(repo, archive);

    const result = runArchiveVerification(repo, archive);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("repo history archive verification passed");
    expect(result.stdout).toContain("fileCount=3");
  });

  test("refuses removal when a source document changed after archive", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-source-change-");
    runArchive(repo, archive);
    write(repo, "docs/old-guide.md", "# Changed after archive\n");

    const result = runArchiveVerification(repo, archive);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain(
      "source historical documents changed after archive; do not remove them"
    );
  });

  test("refuses removal when the archived copy changed", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-target-change-");
    runArchive(repo, archive);
    write(archive, "docs/old-guide.md", "# Damaged archive\n");

    const result = runArchiveVerification(repo, archive);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("archive files do not match recorded hashes");
  });

  test("refuses removal when the tracked historical set changed after archive", () => {
    const repo = createFixtureRepo();
    const archive = newTempDir("prep-watchdeck-archive-manifest-change-");
    runArchive(repo, archive);
    write(repo, "docs/new-history.md", "# Newly tracked history\n");
    execFileSync("git", ["add", "docs/new-history.md"], { cwd: repo });

    const result = runArchiveVerification(repo, archive);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain(
      "archive manifest no longer matches tracked historical documents"
    );
  });
});

describe("shell state path resolver", () => {
  test("derives and exports one absolute state root for scanner and Web", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });
    const stateDir = join(repo, "external-state");

    const result = runStatePathResolver(repo, {
      PREP_WATCHDECK_STATE_DIR: stateDir
    });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(`stateDir=${stateDir}`);
    expect(result.stdout).toContain(`snapshotPath=${join(stateDir, "snapshots", "latest.json")}`);
    expect(result.stdout).toContain(`databasePath=${join(stateDir, "watchdeck.duckdb")}`);
    expect(result.stdout).toContain(
      `serviceStatePath=${join(stateDir, "snapshots", "service-state.json")}`
    );
    expect(result.stdout).toContain(
      `tickerRuntimePath=${join(stateDir, "snapshots", "ticker-runtime.json")}`
    );
    expect(result.stdout).toContain(`chartDir=${join(stateDir, "snapshots", "charts", "latest")}`);
  });

  test("resolves a relative state root from the repository root", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });

    const result = runStatePathResolver(repo, {
      PREP_WATCHDECK_STATE_DIR: "custom-state"
    });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(`stateDir=${join(repo, "custom-state")}`);
  });

  test("bridges a scanner snapshot override to the Web path", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });
    const outDir = join(repo, "custom-snapshots");

    const result = runStatePathResolver(repo, {
      PREP_WATCHDECK_OUT_DIR: outDir
    });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(`snapshotPath=${join(outDir, "latest.json")}`);
    expect(result.stdout).toContain(`scannerSnapshot=${join(outDir, "latest.json")}`);
  });

  test("fails closed when scanner and Web snapshot overrides disagree", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });

    const result = runStatePathResolver(repo, {
      PREP_WATCHDECK_OUT_DIR: join(repo, "scanner-snapshots"),
      SCANNER_SNAPSHOT_PATH: join(repo, "web-snapshots", "latest.json")
    });

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("scanner and Web snapshot paths disagree");
  });

  test("keeps monitoring record overrides without exporting retired record paths", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });

    const result = runStatePathResolver(repo, {
      PREP_WATCHDECK_PAST_NOTES_DIR: "custom-past",
      PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR: "custom-settings"
    });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(
      `pastNotesDir=${join(repo, "apps", "scanner-core", "custom-past")}`
    );
    expect(result.stdout).toContain(
      `dashboardViewSettingsDir=${join(repo, "apps", "scanner-core", "custom-settings")}`
    );
    expect(result.stdout).not.toContain("tradeMemosDir=");
    expect(result.stdout).not.toContain("attackTicketsDir=");
  });

  test("fails closed when a retired record path override is still configured", () => {
    const repo = newTempDir("prep-watchdeck-state-path-repo-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });

    for (const name of [
      "PREP_WATCHDECK_TRADE_MEMOS_DIR",
      "TRADE_MEMOS_DIR",
      "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
      "ATTACK_TICKETS_DIR"
    ]) {
      const result = runStatePathResolver(repo, { [name]: "" });
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain(`retired record state override is no longer supported: ${name}`);
    }
  });
});

describe("daily summary state root", () => {
  test("reads and writes operational data under PREP_WATCHDECK_STATE_DIR", () => {
    const repo = newTempDir("prep-watchdeck-daily-summary-repo-");
    const stateDir = newTempDir("prep-watchdeck-daily-summary-state-");
    write(
      stateDir,
      "snapshots/latest.json",
      `${JSON.stringify({ runId: "external-state", rows: [] })}\n`
    );

    const result = spawnSync(
      "bun",
      [dailySummaryScript, "--repo-root", repo, "--date", "2026-07-16"],
      {
        cwd: repo,
        encoding: "utf-8",
        env: {
          PATH: process.env.PATH,
          HOME: process.env.HOME,
          PREP_WATCHDECK_STATE_DIR: stateDir
        }
      }
    );

    expect(result.status).toBe(0);
    const reportPath = join(stateDir, "ops", "daily", "v2", "2026-07-16.json");
    expect(existsSync(reportPath)).toBe(true);
    expect(existsSync(join(repo, "var", "ops", "daily", "2026-07-16.json"))).toBe(false);
    const report = JSON.parse(readFileSync(reportPath, "utf-8"));
    expect(report.schemaVersion).toBe(2);
    expect(report.stateDir).toBe(stateDir);
    expect(report.summary.snapshot.runId).toBe("external-state");
  });

  test("resolves the Past Note override from scanner-core for daily summaries", () => {
    const repo = newTempDir("prep-watchdeck-daily-summary-repo-");
    const stateDir = newTempDir("prep-watchdeck-daily-summary-state-");
    mkdirSync(join(repo, "apps", "scanner-core"), { recursive: true });
    mkdirSync(join(repo, "apps", "web"), { recursive: true });
    write(
      stateDir,
      "snapshots/latest.json",
      `${JSON.stringify({ runId: "external-state", rows: [] })}\n`
    );
    write(
      repo,
      "apps/scanner-core/custom-past/current.json",
      `${JSON.stringify({ notes: [{ id: "note-1", observedAt: "2026-07-16T00:00:00Z" }] })}\n`
    );

    const result = runDailySummary(repo, stateDir, {
      PREP_WATCHDECK_PAST_NOTES_DIR: "custom-past"
    });

    expect(result.status).toBe(0);
    const report = JSON.parse(
      readFileSync(join(stateDir, "ops", "daily", "v2", "2026-07-16.json"), "utf-8")
    );
    expect(report.summary.annotations.pastNotes).toEqual({ total: 1, onDate: 1 });
  });
});

describe("state directory migration", () => {
  test("copies active state, archives the full source, verifies hashes, and keeps source files", () => {
    const repo = newTempDir("prep-watchdeck-state-migration-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-migration-target-");
    const archive = newTempDir("prep-watchdeck-state-migration-archive-");
    writeStateFixture(source);
    write(repo, "data/scanner.duckdb", "legacy database\n");

    const result = runStateMigration(repo, source, target, archive);

    expect(result.status).toBe(0);
    expect(existsSync(join(target, "watchdeck.duckdb"))).toBe(true);
    expect(existsSync(join(target, "snapshots", "latest.json"))).toBe(true);
    expect(readFileSync(join(archive, "STATE_LAYOUT_VERSION"), "utf-8")).toBe("2\n");
    expect(existsSync(join(target, "trade-memos", "current.json"))).toBe(false);
    expect(existsSync(join(target, "attack-tickets", "current.json"))).toBe(false);
    expect(existsSync(join(archive, "state", "var", "trade-memos", "current.json"))).toBe(
      true
    );
    expect(existsSync(join(archive, "state", "var", "attack-tickets", "current.json"))).toBe(
      true
    );
    expect(
      existsSync(join(target, "past-notes", "archive", "2026-06", "past-notes-2026-06.json"))
    ).toBe(true);
    expect(existsSync(join(target, "backups", "old.duckdb"))).toBe(false);
    expect(existsSync(join(archive, "state", "var", "backups", "old.duckdb"))).toBe(true);
    expect(existsSync(join(archive, "legacy-data", "scanner.duckdb"))).toBe(true);
    expect(existsSync(join(archive, "LEGACY_DATA_SHA256"))).toBe(true);
    expect(existsSync(join(archive, "STATE_COPY_VERIFIED"))).toBe(true);
    expect(existsSync(join(source, "watchdeck.duckdb"))).toBe(true);
    expect(readFileSync(join(source, "past-notes", "current.json"), "utf-8")).toContain(
      "note-1"
    );
  });

  test("refuses a non-empty state target instead of merging unknown data", () => {
    const repo = newTempDir("prep-watchdeck-state-migration-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-migration-target-");
    const archive = newTempDir("prep-watchdeck-state-migration-archive-");
    writeStateFixture(source);
    writeFileSync(join(target, "existing.txt"), "do not overwrite\n");

    const result = runStateMigration(repo, source, target, archive);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("state target must not already contain files");
    expect(readFileSync(join(target, "existing.txt"), "utf-8")).toBe("do not overwrite\n");
  });

  test("fails closed when a chart belongs to a different snapshot run", () => {
    const repo = newTempDir("prep-watchdeck-state-migration-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-migration-target-");
    const archive = newTempDir("prep-watchdeck-state-migration-archive-");
    writeStateFixture(source);
    const migration = runStateMigration(repo, source, target, archive);
    expect(migration.status).toBe(0);

    write(
      target,
      "snapshots/charts/latest/ALTUSDT.json",
      `${JSON.stringify({ snapshotRunId: "different-run" })}\n`
    );
    const result = spawnSync(
      "bash",
      [
        verifyStateScript,
        "--source",
        source,
        "--target",
        target,
        "--archive-dir",
        archive,
        "--mode",
        "cutover"
      ],
      { encoding: "utf-8" }
    );

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("snapshotRunId does not match latest snapshot");
  });

  test("fails v2 cutover when a retained monitoring record count has decreased", () => {
    const repo = newTempDir("prep-watchdeck-state-migration-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-migration-target-");
    const archive = newTempDir("prep-watchdeck-state-migration-archive-");
    writeStateFixture(source);
    const migration = runStateMigration(repo, source, target, archive);
    expect(migration.status).toBe(0);

    write(
      target,
      "past-notes/current.json",
      `${JSON.stringify({ notes: [] })}\n`
    );
    const result = runStateVerification(source, target, archive, "cutover");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("past notes record count decreased");
  });

  test("verifies a markerless v1 archive and still protects retired record counts", () => {
    const fixture = createLegacyV1StateFixture();

    const copy = runStateVerification(
      fixture.source,
      fixture.target,
      fixture.archive,
      "copy"
    );
    expect(copy.status).toBe(0);
    expect(copy.stdout).toContain("layoutVersion=1");
    expect(existsSync(join(fixture.target, "trade-memos/current.json"))).toBe(true);
    expect(existsSync(join(fixture.archive, "STATE_LAYOUT_VERSION"))).toBe(false);

    write(fixture.target, "trade-memos/current.json", `${JSON.stringify({ memos: [] })}\n`);
    const cutover = runStateVerification(
      fixture.source,
      fixture.target,
      fixture.archive,
      "cutover"
    );
    expect(cutover.status).not.toBe(0);
    expect(cutover.stderr).toContain("trade memos record count decreased");
  });

  test("fails closed for invalid or unsupported state layout markers", () => {
    for (const marker of ["1\n", "invalid\n", "3\n"]) {
      const repo = newTempDir("prep-watchdeck-state-version-repo-");
      const source = join(repo, "var");
      const target = newTempDir("prep-watchdeck-state-version-target-");
      const archive = newTempDir("prep-watchdeck-state-version-archive-");
      writeStateFixture(source);
      expect(runStateMigration(repo, source, target, archive).status).toBe(0);
      writeFileSync(join(archive, "STATE_LAYOUT_VERSION"), marker);

      const result = runStateVerification(source, target, archive, "copy");
      expect(result.status).not.toBe(0);
      expect(result.stderr).toContain("unsupported state layout version");
    }
  });

  test("uses SOURCE_ALL evidence to reject matching source and archive corruption", () => {
    const repo = newTempDir("prep-watchdeck-state-all-hash-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-all-hash-target-");
    const archive = newTempDir("prep-watchdeck-state-all-hash-archive-");
    writeStateFixture(source);
    expect(runStateMigration(repo, source, target, archive).status).toBe(0);
    write(source, "backups/old.duckdb", "changed in both copies\n");
    write(archive, "state/var/backups/old.duckdb", "changed in both copies\n");

    const result = runStateVerification(source, target, archive, "copy");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("old source state changed after migration");
  });

  test("rejects extra files added to the full state archive", () => {
    const repo = newTempDir("prep-watchdeck-state-extra-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-extra-target-");
    const archive = newTempDir("prep-watchdeck-state-extra-archive-");
    writeStateFixture(source);
    expect(runStateMigration(repo, source, target, archive).status).toBe(0);
    write(archive, "state/var/unrecorded.txt", "unexpected\n");

    const result = runStateVerification(source, target, archive, "copy");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("archived state file list does not match recorded source manifest");
  });

  test("rejects pairwise nested source, target, and archive paths", () => {
    const repo = newTempDir("prep-watchdeck-state-overlap-repo-");
    const source = newTempDir("prep-watchdeck-state-overlap-source-");
    const archive = newTempDir("prep-watchdeck-state-overlap-archive-");
    writeStateFixture(source);

    const targetInsideSource = runStateMigration(
      repo,
      source,
      join(source, "target"),
      archive
    );
    expect(targetInsideSource.status).not.toBe(0);
    expect(targetInsideSource.stderr).toContain("source, state target, and archive must not overlap");

    const target = newTempDir("prep-watchdeck-state-overlap-target-");
    const archiveInsideTarget = runStateMigration(
      repo,
      source,
      target,
      join(target, "archive")
    );
    expect(archiveInsideTarget.status).not.toBe(0);
    expect(archiveInsideTarget.stderr).toContain("source, state target, and archive must not overlap");
  });

  test("rejects retired record files mixed into a v2 target", () => {
    const repo = newTempDir("prep-watchdeck-state-retired-target-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-retired-target-");
    const archive = newTempDir("prep-watchdeck-state-retired-archive-");
    writeStateFixture(source);
    expect(runStateMigration(repo, source, target, archive).status).toBe(0);
    write(target, "trade-memos/current.json", `${JSON.stringify({ memos: [] })}\n`);

    const result = runStateVerification(source, target, archive, "copy");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("v2 target contains retired record files");
  });

  test("compares retained monitoring files byte-for-byte in a v2 copy", () => {
    const repo = newTempDir("prep-watchdeck-state-common-repo-");
    const source = join(repo, "var");
    const target = newTempDir("prep-watchdeck-state-common-target-");
    const archive = newTempDir("prep-watchdeck-state-common-archive-");
    writeStateFixture(source);
    expect(runStateMigration(repo, source, target, archive).status).toBe(0);
    write(
      target,
      "past-notes/archive/2026-06/past-notes-2026-06.json",
      `${JSON.stringify({ notes: [] })}\n`
    );

    const result = runStateVerification(source, target, archive, "copy");

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("state target hashes do not match source");
  });
});

describe("reorganization finalization", () => {
  test("dry-run verifies every copy and retains all source files", () => {
    const fixture = createFinalizationFixture();

    const result = runFinalization(fixture, false);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("verification=passed");
    expect(result.stdout).toContain("dry-run only");
    expect(existsSync(join(fixture.repo, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "data", "scanner.duckdb"))).toBe(true);
    expect(existsSync(join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED"))).toBe(false);
    expect(
      readdirSync(fixture.historyArchive).some((name) =>
        name.startsWith(".REPO_FINALIZATION_VERIFIED.")
      )
    ).toBe(false);
  });

  test("apply removes only verified history and the legacy database", () => {
    const fixture = createFinalizationFixture();

    const result = runFinalization(fixture, true);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("Repo reorganization finalization applied");
    expect(result.stdout).toContain(
      `finalizationEvidence=${join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED")}`
    );
    expect(existsSync(join(fixture.repo, "docs", "old-guide.md"))).toBe(false);
    expect(existsSync(join(fixture.repo, "docs", "archive", "older.md"))).toBe(false);
    expect(existsSync(join(fixture.repo, "mockups", "concept", "index.html"))).toBe(false);
    expect(existsSync(join(fixture.repo, "data", "scanner.duckdb"))).toBe(false);
    expect(existsSync(join(fixture.repo, "docs", "README.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "docs", "current", "overview.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "var", "watchdeck.duckdb"))).toBe(true);
    expect(existsSync(join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED"))).toBe(true);
    const evidence = readFileSync(
      join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED"),
      "utf-8"
    );
    expect(evidence).toContain("preparedAt=");
    expect(evidence).toContain("finalizedAt=");
    expect(evidence).toContain("historicalFilesPlanned=3");
    expect(evidence).toContain("historicalFilesRemoved=3");
    expect(
      readdirSync(fixture.historyArchive).some((name) =>
        name.startsWith(".REPO_FINALIZATION_VERIFIED.")
      )
    ).toBe(false);
  });

  test("refuses removal when finalization evidence cannot be prepared", () => {
    const fixture = createFinalizationFixture();
    chmodSync(fixture.historyArchive, 0o555);

    let result;
    try {
      result = runFinalization(fixture, true);
    } finally {
      chmodSync(fixture.historyArchive, 0o755);
    }

    expect(result.status).not.toBe(0);
    expect(existsSync(join(fixture.repo, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "docs", "archive", "older.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "mockups", "concept", "index.html"))).toBe(true);
    expect(existsSync(join(fixture.repo, "data", "scanner.duckdb"))).toBe(true);
    expect(existsSync(join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED"))).toBe(false);
    expect(result.stderr).toContain("cannot prepare Repo finalization evidence");
  });

  test("retains pending evidence when removal fails after it starts", () => {
    const fixture = createFinalizationFixture();
    const fakeBin = newTempDir("prep-watchdeck-finalize-fake-bin-");
    write(
      fakeBin,
      "rm",
      [
        "#!/usr/bin/env bash",
        'for argument in "$@"; do',
        '  case "$argument" in',
        "    */docs/old-guide.md)",
        '      echo "injected removal failure: $argument" >&2',
        "      exit 73",
        "      ;;",
        "  esac",
        "done",
        'exec /usr/bin/rm "$@"',
        ""
      ].join("\n")
    );
    chmodSync(join(fakeBin, "rm"), 0o755);

    const result = runFinalization(fixture, true, {
      PATH: `${fakeBin}:${process.env.PATH}`
    });

    expect(result.status).not.toBe(0);
    expect(existsSync(join(fixture.repo, "docs", "archive", "older.md"))).toBe(false);
    expect(existsSync(join(fixture.repo, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "mockups", "concept", "index.html"))).toBe(true);
    expect(existsSync(join(fixture.repo, "data", "scanner.duckdb"))).toBe(true);
    expect(existsSync(join(fixture.historyArchive, "REPO_FINALIZATION_VERIFIED"))).toBe(false);
    const pendingEvidence = readdirSync(fixture.historyArchive).filter((name) =>
      name.startsWith(".REPO_FINALIZATION_VERIFIED.")
    );
    expect(pendingEvidence).toHaveLength(1);
    const evidence = readFileSync(join(fixture.historyArchive, pendingEvidence[0]), "utf-8");
    expect(evidence).toContain("preparedAt=");
    expect(evidence).not.toContain("finalizedAt=");
    expect(result.stderr).toContain("injected removal failure");
    expect(result.stderr).toContain("pending Repo finalization evidence retained");
  });

  test("refuses removal when state cutover evidence is no longer valid", () => {
    const fixture = createFinalizationFixture();
    write(
      fixture.stateTarget,
      "past-notes/current.json",
      `${JSON.stringify({ notes: [] })}\n`
    );

    const result = runFinalization(fixture, true);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("past notes record count decreased");
    expect(existsSync(join(fixture.repo, "docs", "old-guide.md"))).toBe(true);
    expect(existsSync(join(fixture.repo, "data", "scanner.duckdb"))).toBe(true);
  });
});

function createFixtureRepo() {
  const root = newTempDir("prep-watchdeck-archive-repo-");
  write(root, "docs/README.md", "# Index\n");
  write(root, "docs/current/overview.md", "# Current\n");
  write(root, "docs/decisions/0001-local.md", "# Decision\n");
  write(root, "docs/plans/active/current-plan.md", "# Plan\n");
  write(root, "docs/old-guide.md", "# Old\n");
  write(root, "docs/archive/older.md", "# Older\n");
  write(root, "mockups/concept/index.html", "<html></html>\n");
  write(root, "src/app.ts", "export {};\n");

  execFileSync("git", ["init", "-q"], { cwd: root });
  execFileSync("git", ["add", "."], { cwd: root });
  return root;
}

function createFinalizationFixture() {
  const repo = createFixtureRepo();
  const stateTarget = newTempDir("prep-watchdeck-finalize-target-");
  const stateArchive = newTempDir("prep-watchdeck-finalize-state-archive-");
  const historyArchive = newTempDir("prep-watchdeck-finalize-history-archive-");
  writeStateFixture(join(repo, "var"));
  write(repo, "data/scanner.duckdb", "legacy database\n");
  runArchive(repo, historyArchive);
  const migration = runStateMigration(
    repo,
    join(repo, "var"),
    stateTarget,
    stateArchive
  );
  if (migration.status !== 0) {
    throw new Error(
      `state migration failed\nstdout:\n${migration.stdout}\nstderr:\n${migration.stderr}`
    );
  }
  return { repo, stateTarget, stateArchive, historyArchive };
}

function runArchive(repo, archive) {
  const result = spawnSync(
    "bash",
    [archiveScript, "--repo-root", repo, "--archive-dir", archive],
    { encoding: "utf-8" }
  );
  if (result.status !== 0) {
    throw new Error(`archive failed\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`);
  }
}

function runArchiveVerification(repo, archive) {
  return spawnSync(
    "bash",
    [verifyArchiveScript, "--repo-root", repo, "--archive-dir", archive],
    { encoding: "utf-8" }
  );
}

function runFinalization(fixture, apply, env = {}) {
  return spawnSync(
    "bash",
    [
      finalizeReorganizationScript,
      "--repo-root",
      fixture.repo,
      "--repo-history-archive",
      fixture.historyArchive,
      "--state-target",
      fixture.stateTarget,
      "--state-archive-dir",
      fixture.stateArchive,
      ...(apply ? ["--apply"] : [])
    ],
    {
      encoding: "utf-8",
      env: {
        ...process.env,
        ...env
      }
    }
  );
}

function runStatePathResolver(repo, env) {
  return spawnSync(
    "bash",
    [
      "-c",
      [
        "set -e",
        'source "$1"',
        'resolve_watchdeck_state_paths "$2"',
        'print_watchdeck_state_paths',
        'printf "scannerSnapshot=%s\\n" "$SCANNER_SNAPSHOT_PATH"',
        'printf "pastNotesDir=%s\\n" "$WATCHDECK_PAST_NOTES_DIR"',
        'printf "dashboardViewSettingsDir=%s\\n" "$WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR"'
      ].join("\n"),
      "_",
      statePathScript,
      repo
    ],
    {
      encoding: "utf-8",
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        ...env
      }
    }
  );
}

function runStateMigration(repo, source, target, archive) {
  return spawnSync(
    "bash",
    [
      migrateStateScript,
      "--repo-root",
      repo,
      "--source",
      source,
      "--target",
      target,
      "--archive-dir",
      archive
    ],
    {
      encoding: "utf-8",
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        PREP_WATCHDECK_MIGRATION_SKIP_PROCESS_CHECK: "1"
      }
    }
  );
}

function runDailySummary(repo, stateDir, env = {}) {
  return spawnSync(
    "bun",
    [dailySummaryScript, "--repo-root", repo, "--date", "2026-07-16"],
    {
      cwd: repo,
      encoding: "utf-8",
      env: {
        PATH: process.env.PATH,
        HOME: process.env.HOME,
        PREP_WATCHDECK_STATE_DIR: stateDir,
        ...env
      }
    }
  );
}

function runStateVerification(source, target, archive, mode) {
  return spawnSync(
    "bash",
    [
      verifyStateScript,
      "--source",
      source,
      "--target",
      target,
      "--archive-dir",
      archive,
      "--mode",
      mode
    ],
    { encoding: "utf-8" }
  );
}

function writeStateFixture(source) {
  write(source, "watchdeck.duckdb", "database\n");
  write(source, "watchdeck.duckdb.wal", "wal\n");
  write(
    source,
    "snapshots/latest.json",
    `${JSON.stringify({ runId: "run-1", rows: [{ symbol: "ALTUSDT" }] })}\n`
  );
  write(
    source,
    "snapshots/charts/latest/ALTUSDT.json",
    `${JSON.stringify({ snapshotRunId: "run-1", symbol: "ALTUSDT" })}\n`
  );
  write(
    source,
    "past-notes/current.json",
    `${JSON.stringify({ notes: [{ id: "note-1" }] })}\n`
  );
  write(
    source,
    "past-notes/archive/2026-06/past-notes-2026-06.json",
    `${JSON.stringify({ notes: [{ id: "archived-note-1" }] })}\n`
  );
  write(
    source,
    "trade-memos/current.json",
    `${JSON.stringify({ memos: [{ id: "memo-1" }] })}\n`
  );
  write(
    source,
    "attack-tickets/current.json",
    `${JSON.stringify({ tickets: [{ id: "ticket-1" }] })}\n`
  );
  write(
    source,
    "dashboard-view-settings/current.json",
    `${JSON.stringify({ schemaVersion: 1, views: {} })}\n`
  );
  write(source, "backups/old.duckdb", "archive only\n");
  write(source, "performance/evidence.json", "{}\n");
  write(source, "usage-events/2026-07-16.ndjson", "{\"ts\":\"now\",\"event\":\"app_loaded\"}\n");
  write(source, "ops/daily/2026-07-16.json", "{\"schemaVersion\":1}\n");
}

function createLegacyV1StateFixture() {
  const repo = newTempDir("prep-watchdeck-state-v1-repo-");
  const source = join(repo, "var");
  const target = newTempDir("prep-watchdeck-state-v1-target-");
  const archive = newTempDir("prep-watchdeck-state-v1-archive-");
  writeStateFixture(source);
  const allFiles = listRegularFiles(source);
  const activeFiles = allFiles.filter(isV1ActiveStateFile);

  for (const relativePath of allFiles) {
    copyFixtureFile(source, join(archive, "state", "var"), relativePath);
  }
  for (const relativePath of activeFiles) {
    copyFixtureFile(source, target, relativePath);
  }
  writeFileSync(join(archive, "SOURCE_ALL_MANIFEST.txt"), `${allFiles.join("\n")}\n`);
  writeFileSync(join(archive, "SOURCE_ACTIVE_MANIFEST.txt"), `${activeFiles.join("\n")}\n`);
  writeFileSync(join(archive, "SOURCE_ALL_SHA256"), hashFixtureFiles(source, allFiles));
  writeFileSync(join(archive, "SOURCE_ACTIVE_SHA256"), hashFixtureFiles(source, activeFiles));
  return { repo, source, target, archive };
}

function isV1ActiveStateFile(path) {
  return (
    path === "watchdeck.duckdb" ||
    path === "watchdeck.duckdb.wal" ||
    [
      "snapshots/",
      "past-notes/",
      "trade-memos/",
      "attack-tickets/",
      "dashboard-view-settings/",
      "usage-events/",
      "ops/"
    ].some((prefix) => path.startsWith(prefix))
  );
}

function listRegularFiles(root, relativeRoot = "") {
  const directory = join(root, relativeRoot);
  return readdirSync(directory, { withFileTypes: true })
    .flatMap((entry) => {
      const relativePath = relativeRoot ? `${relativeRoot}/${entry.name}` : entry.name;
      if (entry.isDirectory()) return listRegularFiles(root, relativePath);
      return entry.isFile() ? [relativePath] : [];
    })
    .sort();
}

function copyFixtureFile(source, target, relativePath) {
  const destination = join(target, relativePath);
  mkdirSync(dirname(destination), { recursive: true });
  copyFileSync(join(source, relativePath), destination);
}

function hashFixtureFiles(root, files) {
  return files
    .map((relativePath) => {
      const hash = createHash("sha256").update(readFileSync(join(root, relativePath))).digest("hex");
      return `${hash}  ${relativePath}`;
    })
    .join("\n") + "\n";
}

function write(root, relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(resolve(path, ".."), { recursive: true });
  writeFileSync(path, content);
}

function newTempDir(prefix) {
  const root = mkdtempSync(join(tmpdir(), prefix));
  createdRoots.push(root);
  return root;
}
