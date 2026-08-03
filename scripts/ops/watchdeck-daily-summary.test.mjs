import { afterEach, describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const dailySummaryScript = resolve(import.meta.dirname, "watchdeck-daily-summary.mjs");
const createdRoots = [];
const date = "2026-08-02";

afterEach(() => {
  for (const root of createdRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("monitoring-only daily summary v2", () => {
  test("writes a versioned monitoring report without reading retired records or overwriting v1", () => {
    const fixture = createFixture();
    write(fixture.state, `ops/daily/${date}.json`, '{"schemaVersion":1,"sentinel":"keep"}\n');
    write(fixture.state, `ops/daily/${date}.md`, "legacy v1 review\n");
    write(
      fixture.state,
      "snapshots/latest.json",
      JSON.stringify({
        runId: "monitoring-run",
        generatedAt: 1_785_600_000_000,
        dataAsOf: 1_785_600_000_000,
        snapshotStatus: "COMPLETE",
        source: { dataSource: "fixture", templateName: "balanced", isFallback: false },
        rows: []
      }) + "\n"
    );
    write(
      fixture.state,
      "past-notes/current.json",
      JSON.stringify({
        notes: [
          {
            symbol: "ALTUSDT",
            reason: "monitor",
            observedAt: "2026-08-02T01:00:00.000Z",
            createdAt: "2026-08-01T01:00:00.000Z"
          },
          {
            symbol: "OLDUSDT",
            reason: "old",
            observedAt: "2026-08-01T01:00:00.000Z",
            createdAt: "2026-08-02T01:00:00.000Z"
          }
        ]
      }) + "\n"
    );
    write(
      fixture.state,
      "dashboard-view-settings/current.json",
      JSON.stringify({
        schemaVersion: 1,
        updatedAt: "2026-08-02T02:00:00.000Z",
        views: { desktop: {}, mobile: {} }
      }) + "\n"
    );
    write(fixture.repo, "retired/trade/current.json", "this must not be parsed\n");
    write(fixture.repo, "retired/attack/current.json", "this must not be parsed\n");

    const result = runSummary(fixture, ["--write-markdown"], {
      PREP_WATCHDECK_TRADE_MEMOS_DIR: resolve(fixture.repo, "retired/trade"),
      PREP_WATCHDECK_ATTACK_TICKETS_DIR: resolve(fixture.repo, "retired/attack")
    });

    expect(result.status).toBe(0);
    expect(readFileSync(join(fixture.state, `ops/daily/${date}.json`), "utf-8")).toBe(
      '{"schemaVersion":1,"sentinel":"keep"}\n'
    );
    expect(readFileSync(join(fixture.state, `ops/daily/${date}.md`), "utf-8")).toBe(
      "legacy v1 review\n"
    );
    const reportPath = join(fixture.state, `ops/daily/v2/${date}.json`);
    const markdownPath = join(fixture.state, `ops/daily/v2/${date}.md`);
    expect(existsSync(reportPath)).toBe(true);
    expect(existsSync(markdownPath)).toBe(true);

    const reportText = readFileSync(reportPath, "utf-8");
    const report = JSON.parse(reportText);
    expect(report.schemaVersion).toBe(2);
    expect(Object.keys(report.sourceFiles).sort()).toEqual([
      "dashboardSettings",
      "pastNotes",
      "snapshot",
      "usageEvents"
    ]);
    expect(reportText).not.toContain("tradeMemos");
    expect(reportText).not.toContain("attackTickets");
    expect(report.summary.annotations.pastNotes).toEqual({ total: 2, onDate: 1 });
    expect(report.summary.dashboardSettings.editableViewCount).toBe(2);
    expect(report.summary.snapshot.runId).toBe("monitoring-run");
    expect(report.notes).toContain(
      "usage event log is missing; no usage event producer is implemented, so monitoring operation counts are zero."
    );

    const markdown = readFileSync(markdownPath, "utf-8");
    expect(markdown).toContain("# 監視日次サマリー");
    expect(markdown).not.toContain("TRADE");
    expect(markdown).not.toContain("SKIP");
    expect(markdown).not.toContain("Attack Ticket");
  });

  test("classifies monitoring, retired, unknown, and structurally invalid usage lines separately", () => {
    const fixture = createFixture();
    write(
      fixture.state,
      `usage-events/${date}.ndjson`,
      [
        JSON.stringify({ ts: "2026-08-02T00:00:00Z", event: "app_loaded" }),
        JSON.stringify({
          ts: "2026-08-02T00:01:00Z",
          event: "raw_sort_changed",
          timeframe: "4h",
          sortKey: "changePct",
          direction: "desc"
        }),
        JSON.stringify({ ts: "2026-08-02T00:02:00Z", event: "trade_memo_saved" }),
        JSON.stringify({ ts: "2026-08-02T00:03:00Z", event: "future_monitor_event" }),
        JSON.stringify({ ts: 123, event: "app_loaded" }),
        JSON.stringify({ event: "app_loaded" }),
        "not-json",
        ""
      ].join("\n")
    );

    const result = runSummary(fixture);

    expect(result.status).toBe(0);
    const report = readReport(fixture);
    expect(report.sourceFiles.usageEvents).toMatchObject({
      exists: true,
      valid: false,
      lineCount: 7,
      validLines: 4,
      invalidLines: 3
    });
    expect(report.summary.usageEvents.totalEvents).toBe(2);
    expect(report.summary.usageEvents.eventCounts).toEqual({
      app_loaded: 1,
      raw_sort_changed: 1
    });
    expect(report.summary.usageEvents.legacyRetiredEventCounts).toEqual({
      trade_memo_saved: 1
    });
    expect(report.summary.usageEvents.unknownEventCounts).toEqual({
      future_monitor_event: 1
    });
    expect(report.summary.usageEvents.rawSortTop).toEqual([
      { timeframe: "4h", sortKey: "changePct", direction: "desc", count: 1 }
    ]);
  });

  test("does not mark well-formed legacy or unknown events as invalid lines", () => {
    const fixture = createFixture();
    write(
      fixture.state,
      `usage-events/${date}.ndjson`,
      [
        JSON.stringify({ ts: "2026-08-02T00:00:00Z", event: "quick_skip_saved" }),
        JSON.stringify({ ts: "2026-08-02T00:01:00Z", event: "future_event" }),
        ""
      ].join("\n")
    );

    const result = runSummary(fixture);

    expect(result.status).toBe(0);
    const report = readReport(fixture);
    expect(report.sourceFiles.usageEvents).toMatchObject({
      valid: true,
      validLines: 2,
      invalidLines: 0
    });
    expect(report.summary.usageEvents.eventCounts).toEqual({});
    expect(report.summary.usageEvents.legacyRetiredEventCounts).toEqual({
      quick_skip_saved: 1
    });
    expect(report.summary.usageEvents.unknownEventCounts).toEqual({ future_event: 1 });
  });
});

function createFixture() {
  const repo = newTempDir("prep-watchdeck-daily-v2-repo-");
  const state = newTempDir("prep-watchdeck-daily-v2-state-");
  mkdirSync(join(repo, "apps/scanner-core"), { recursive: true });
  mkdirSync(join(repo, "apps/web"), { recursive: true });
  return { repo, state };
}

function runSummary(fixture, args = [], env = {}) {
  const cleanEnv = { ...process.env };
  for (const name of [
    "PREP_WATCHDECK_STATE_DIR",
    "PREP_WATCHDECK_OUT_DIR",
    "SCANNER_SNAPSHOT_PATH",
    "PREP_WATCHDECK_PAST_NOTES_DIR",
    "PAST_NOTES_DIR",
    "PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR",
    "PREP_WATCHDECK_TRADE_MEMOS_DIR",
    "TRADE_MEMOS_DIR",
    "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
    "ATTACK_TICKETS_DIR"
  ]) {
    delete cleanEnv[name];
  }
  return spawnSync(
    "bun",
    [dailySummaryScript, "--repo-root", fixture.repo, "--date", date, ...args],
    {
      cwd: fixture.repo,
      encoding: "utf-8",
      env: {
        ...cleanEnv,
        PREP_WATCHDECK_STATE_DIR: fixture.state,
        ...env
      }
    }
  );
}

function readReport(fixture) {
  return JSON.parse(
    readFileSync(join(fixture.state, `ops/daily/v2/${date}.json`), "utf-8")
  );
}

function write(root, relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function newTempDir(prefix) {
  const root = mkdtempSync(join(tmpdir(), prefix));
  createdRoots.push(root);
  return root;
}
