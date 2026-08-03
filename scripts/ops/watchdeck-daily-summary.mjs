#!/usr/bin/env node

import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const defaultRepoRoot = resolve(scriptDir, "..", "..");

const MONITORING_USAGE_EVENT_NAMES = [
  "app_loaded",
  "snapshot_loaded",
  "raw_sort_changed",
  "dashboard_view_changed",
  "smart_rank_run",
  "dashboard_settings_saved"
];

const RETIRED_USAGE_EVENT_NAMES = [
  "quick_skip_saved",
  "attack_ticket_saved",
  "trade_memo_saved",
  "weekly_review_opened",
  "record_save_failed"
];

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    printHelp();
    return;
  }

  const repoRoot = resolve(options.repoRoot ?? defaultRepoRoot);
  const date = options.date ?? formatLocalDate(new Date());
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error(`invalid --date: ${date}`);
  }

  const paths = buildPaths(repoRoot, date, process.env);
  const [usageEvents, pastNotes, dashboardSettings, snapshot] = await Promise.all([
    readNdjsonSource(paths.usageEvents, repoRoot),
    readJsonSource(paths.pastNotes, repoRoot),
    readJsonSource(paths.dashboardSettings, repoRoot),
    readJsonSource(paths.snapshot, repoRoot)
  ]);

  const report = buildReport({
    date,
    repoRoot,
    stateDir: paths.stateDir,
    generatedAt: new Date().toISOString(),
    sources: {
      usageEvents,
      pastNotes,
      dashboardSettings,
      snapshot
    }
  });

  await writeJsonAtomic(paths.outputJson, report);
  console.log(`daily summary: ${relative(repoRoot, paths.outputJson)}`);

  if (options.writeMarkdown) {
    await writeTextAtomic(paths.outputMarkdown, renderMarkdown(report));
    console.log(`markdown review: ${relative(repoRoot, paths.outputMarkdown)}`);
  }
}

function parseArgs(argv) {
  const options = {
    date: null,
    repoRoot: null,
    writeMarkdown: false,
    help: false
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      options.help = true;
    } else if (arg === "--write-markdown" || arg === "--markdown") {
      options.writeMarkdown = true;
    } else if (arg === "--date") {
      options.date = requireValue(argv, (index += 1), arg);
    } else if (arg.startsWith("--date=")) {
      options.date = arg.slice("--date=".length);
    } else if (arg === "--repo-root") {
      options.repoRoot = requireValue(argv, (index += 1), arg);
    } else if (arg.startsWith("--repo-root=")) {
      options.repoRoot = arg.slice("--repo-root=".length);
    } else {
      throw new Error(`unknown option: ${arg}`);
    }
  }

  return options;
}

function requireValue(argv, index, optionName) {
  const value = argv[index];
  if (!value || value.startsWith("--")) {
    throw new Error(`${optionName} requires a value`);
  }
  return value;
}

function printHelp() {
  console.log(`Usage: bun scripts/ops/watchdeck-daily-summary.mjs [options]

Options:
  --date YYYY-MM-DD       Target local date. Defaults to today.
  --write-markdown        Also write the review beside the JSON under the state directory.
  --repo-root PATH        Repo root. Defaults to this script's repo.
  -h, --help              Show this help.

Default output:
  <resolved-state-root>/ops/daily/v2/YYYY-MM-DD.json
  Defaults to <repo-root>/var/ops/daily/v2/YYYY-MM-DD.json when PREP_WATCHDECK_STATE_DIR is unset.
`);
}

function buildPaths(repoRoot, date, env) {
  const scannerRoot = resolve(repoRoot, "apps", "scanner-core");
  const webRoot = resolve(repoRoot, "apps", "web");
  const stateDir = resolve(repoRoot, env.PREP_WATCHDECK_STATE_DIR ?? "var");
  const scannerSnapshotPath = env.PREP_WATCHDECK_OUT_DIR
    ? resolve(scannerRoot, env.PREP_WATCHDECK_OUT_DIR, "latest.json")
    : undefined;
  const webSnapshotPath = env.SCANNER_SNAPSHOT_PATH
    ? resolve(webRoot, env.SCANNER_SNAPSHOT_PATH)
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

  return {
    stateDir,
    usageEvents: resolve(stateDir, "usage-events", `${date}.ndjson`),
    pastNotes: resolveRecordPath(
      scannerRoot,
      webRoot,
      stateDir,
      env.PREP_WATCHDECK_PAST_NOTES_DIR,
      env.PAST_NOTES_DIR,
      "past-notes"
    ),
    dashboardSettings: resolveRecordPath(
      scannerRoot,
      webRoot,
      stateDir,
      env.PREP_WATCHDECK_DASHBOARD_VIEW_SETTINGS_DIR,
      undefined,
      "dashboard-view-settings"
    ),
    snapshot: snapshotPath,
    outputJson: resolve(stateDir, "ops", "daily", "v2", `${date}.json`),
    outputMarkdown: resolve(stateDir, "ops", "daily", "v2", `${date}.md`)
  };
}

function resolveRecordPath(
  scannerRoot,
  webRoot,
  stateDir,
  prefixedOverride,
  legacyOverride,
  defaultDirectory
) {
  let directory = resolve(stateDir, defaultDirectory);
  if (legacyOverride) directory = resolve(webRoot, legacyOverride);
  if (prefixedOverride) directory = resolve(scannerRoot, prefixedOverride);
  return resolve(directory, "current.json");
}

function assertMatchingPaths(label, first, second) {
  if (first !== undefined && second !== undefined && first !== second) {
    throw new Error(`${label} disagree: ${first} != ${second}`);
  }
}
async function readJsonSource(path, repoRoot) {
  const source = {
    path: relative(repoRoot, path),
    exists: false,
    valid: false,
    bytes: 0,
    error: null
  };

  try {
    const text = await readFile(path, "utf-8");
    source.exists = true;
    source.bytes = Buffer.byteLength(text, "utf-8");
    return {
      source: { ...source, valid: true },
      data: JSON.parse(text)
    };
  } catch (cause) {
    const code = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
    if (code === "ENOENT") {
      return { source, data: null };
    }
    return {
      source: {
        ...source,
        exists: true,
        error: cause instanceof Error ? cause.message : String(cause)
      },
      data: null
    };
  }
}

async function readNdjsonSource(path, repoRoot) {
  const source = {
    path: relative(repoRoot, path),
    exists: false,
    valid: false,
    bytes: 0,
    lineCount: 0,
    validLines: 0,
    invalidLines: 0,
    error: null
  };

  try {
    const text = await readFile(path, "utf-8");
    const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
    const events = [];
    let invalidLines = 0;

    for (const line of lines) {
      try {
        const event = JSON.parse(line);
        if (isUsageEventShape(event)) {
          events.push(event);
        } else {
          invalidLines += 1;
        }
      } catch {
        invalidLines += 1;
      }
    }

    return {
      source: {
        ...source,
        exists: true,
        valid: invalidLines === 0,
        bytes: Buffer.byteLength(text, "utf-8"),
        lineCount: lines.length,
        validLines: events.length,
        invalidLines
      },
      events
    };
  } catch (cause) {
    const code = cause && typeof cause === "object" && "code" in cause ? cause.code : null;
    if (code === "ENOENT") {
      return { source, events: [] };
    }
    return {
      source: {
        ...source,
        exists: true,
        error: cause instanceof Error ? cause.message : String(cause)
      },
      events: []
    };
  }
}

function isUsageEventShape(value) {
  return (
    value &&
    typeof value === "object" &&
    typeof value.ts === "string" &&
    typeof value.event === "string"
  );
}

function buildReport({ date, repoRoot, stateDir, generatedAt, sources }) {
  const usageSummary = summarizeUsageEvents(sources.usageEvents.events);
  const annotationSummary = summarizeAnnotations({ date, pastNotes: sources.pastNotes.data });
  const dashboardSettingsSummary = summarizeDashboardSettings(sources.dashboardSettings);
  const snapshotSummary = summarizeSnapshot(sources.snapshot.data);

  return {
    schemaVersion: 2,
    generatedAt,
    generatedBy: "scripts/ops/watchdeck-daily-summary.mjs",
    date,
    repoRoot,
    stateDir,
    sourceFiles: {
      usageEvents: sources.usageEvents.source,
      pastNotes: sources.pastNotes.source,
      dashboardSettings: sources.dashboardSettings.source,
      snapshot: sources.snapshot.source
    },
    summary: {
      usageEvents: usageSummary,
      annotations: annotationSummary,
      dashboardSettings: dashboardSettingsSummary,
      snapshot: snapshotSummary
    },
    notes: buildNotes({ sources, usageSummary, snapshotSummary })
  };
}

function summarizeUsageEvents(events) {
  const monitoringEvents = events.filter((event) =>
    MONITORING_USAGE_EVENT_NAMES.includes(event.event)
  );
  const legacyRetiredEvents = events.filter((event) =>
    RETIRED_USAGE_EVENT_NAMES.includes(event.event)
  );
  const unknownEvents = events.filter(
    (event) =>
      !MONITORING_USAGE_EVENT_NAMES.includes(event.event) &&
      !RETIRED_USAGE_EVENT_NAMES.includes(event.event)
  );
  const eventCounts = countBy(monitoringEvents, (event) => event.event);
  const legacyRetiredEventCounts = countBy(legacyRetiredEvents, (event) => event.event);
  const unknownEventCounts = countBy(unknownEvents, (event) => event.event);
  const rawSortCombos = monitoringEvents
    .filter((event) => event.event === "raw_sort_changed")
    .map((event) => ({
      timeframe: stringOrUnknown(event.timeframe),
      sortKey: stringOrUnknown(event.sortKey),
      direction: stringOrUnknown(event.direction)
    }));

  return {
    producerImplemented: false,
    totalEvents: monitoringEvents.length,
    totalValidEvents: events.length,
    eventCounts,
    legacyRetiredEventCounts,
    unknownEventCounts,
    legacyRetiredEventCount: legacyRetiredEvents.length,
    unknownEventCount: unknownEvents.length,
    rawSortChangeCount: eventCounts.raw_sort_changed ?? 0,
    rawSortTop: topCounts(
      rawSortCombos,
      (item) => `${item.timeframe} ${item.sortKey} ${item.direction}`,
      10
    ).map((item) => {
      const [timeframe, sortKey, direction] = item.key.split(" ");
      return { timeframe, sortKey, direction, count: item.count };
    }),
    smartRankRunCount: eventCounts.smart_rank_run ?? 0,
    dashboardSettingsSavedCount: eventCounts.dashboard_settings_saved ?? 0
  };
}

function summarizeAnnotations({ date, pastNotes }) {
  const notes = Array.isArray(pastNotes?.notes) ? pastNotes.notes : [];
  const notesOnDate = notes.filter((note) => localDateFromIso(note.observedAt) === date);

  return {
    pastNotes: {
      total: notes.length,
      onDate: notesOnDate.length
    }
  };
}

function summarizeDashboardSettings(dashboardSettings) {
  const settings = dashboardSettings.data;
  const settingsViews = settings && typeof settings === "object" && settings.views ? settings.views : null;

  return {
    exists: dashboardSettings.source.exists,
    valid: !dashboardSettings.source.exists || dashboardSettings.source.valid,
    usesDefaults: !dashboardSettings.source.exists,
    schemaVersion: settings?.schemaVersion ?? null,
    updatedAt: settings?.updatedAt ?? null,
    editableViewCount:
      settingsViews && typeof settingsViews === "object" && !Array.isArray(settingsViews)
        ? Object.keys(settingsViews).length
        : 0
  };
}

function summarizeSnapshot(snapshot) {
  const rows = Array.isArray(snapshot?.rows) ? snapshot.rows : [];
  const riskTagTop = topCounts(
    rows.flatMap((row) => (Array.isArray(row.riskTagCodes) ? row.riskTagCodes : [])),
    (code) => code,
    10
  );

  return {
    exists: Boolean(snapshot),
    valid: Boolean(snapshot && typeof snapshot === "object" && Array.isArray(snapshot.rows)),
    runId: snapshot?.runId ?? null,
    generatedAt: snapshot?.generatedAt ?? null,
    dataAsOf: snapshot?.dataAsOf ?? null,
    snapshotStatus: snapshot?.snapshotStatus ?? null,
    source: snapshot?.source
      ? {
          dataSource: snapshot.source.dataSource ?? null,
          templateName: snapshot.source.templateName ?? null,
          fixtureSet: snapshot.source.fixtureSet ?? null,
          isFallback: snapshot.source.isFallback ?? null
        }
      : null,
    rowCount: rows.length,
    dataQualityCounts: countBy(rows, (row) => row.dataQuality ?? "unknown"),
    categoryCounts: countBy(rows, (row) => row.category ?? "unknown"),
    riskTagTop
  };
}

function buildNotes({ sources, usageSummary, snapshotSummary }) {
  const notes = [];

  if (!sources.usageEvents.source.exists) {
    notes.push(
      "usage event log is missing; no usage event producer is implemented, so monitoring operation counts are zero."
    );
  } else if (!sources.usageEvents.source.valid) {
    notes.push("usage event log has invalid lines; only valid events were counted.");
  }

  for (const [name, source] of Object.entries({
    pastNotes: sources.pastNotes.source,
    snapshot: sources.snapshot.source
  })) {
    if (source.exists && !source.valid) notes.push(`${name} file is invalid JSON.`);
  }

  if (!sources.snapshot.source.exists) notes.push("snapshot file is missing.");
  if (!sources.dashboardSettings.source.exists) {
    notes.push("dashboard settings file is missing; app defaults are assumed.");
  } else if (!sources.dashboardSettings.source.valid) {
    notes.push("dashboard settings file is invalid JSON.");
  }

  if (usageSummary.legacyRetiredEventCount > 0)
    notes.push("legacy retired usage events were retained as historical counts.");
  if (usageSummary.unknownEventCount > 0)
    notes.push("unknown usage events were counted separately without treating them as invalid lines.");
  if (!snapshotSummary.valid) {
    notes.push("snapshot was not available as a valid scanner snapshot.");
  }

  return notes;
}

function renderMarkdown(report) {
  const annotations = report.summary.annotations;
  const dashboardSettings = report.summary.dashboardSettings;
  const usage = report.summary.usageEvents;
  const snapshot = report.summary.snapshot;
  const dataQualityRows = Object.entries(snapshot.dataQualityCounts)
    .map(([key, value]) => `| ${key} | ${value} |`)
    .join("\n");
  const riskTagLines =
    snapshot.riskTagTop.length > 0
      ? snapshot.riskTagTop.map((item) => `- ${item.key}: ${item.count}`).join("\n")
      : "- なし";
  const rawSortLines =
    usage.rawSortTop.length > 0
      ? usage.rawSortTop
          .map((item) => `- ${item.timeframe} ${item.sortKey} ${item.direction}: ${item.count}`)
          .join("\n")
      : "- usage event logなし";
  const notes =
    report.notes.length > 0 ? report.notes.map((note) => `- ${note}`).join("\n") : "- なし";

  return `# 監視日次サマリー ${report.date}

生成: ${report.generatedAt}

このMarkdownはdeterministic summaryから生成した任意レビューである。正本は\`${report.stateDir}/ops/daily/v2/${report.date}.json\`。

## 自動集計

| 項目 | 値 |
| --- | ---: |
| Raw Sort変更 | ${usage.rawSortChangeCount} |
| Smart Rank実行 | ${usage.smartRankRunCount} |
| Dashboard設定保存 | ${usage.dashboardSettingsSavedCount} |
| Past Note観測 | ${annotations.pastNotes.onDate} |
| Dashboard view数 | ${dashboardSettings.editableViewCount} |

## Snapshot

| 項目 | 値 |
| --- | ---: |
| rows | ${snapshot.rowCount} |
| status | ${snapshot.snapshotStatus ?? "unknown"} |
| dataSource | ${snapshot.source?.dataSource ?? "unknown"} |

## dataQuality

| dataQuality | rows |
| --- | ---: |
${dataQualityRows || "| なし | 0 |"}

## risk tag 上位

${riskTagLines}

## よく使ったRaw Sort

${rawSortLines}

## 注意

${notes}
`;
}

function topCounts(items, keyFn, limit) {
  return Object.entries(countBy(items, keyFn))
    .map(([key, count]) => ({ key, count }))
    .sort((left, right) => {
      if (left.count === right.count) return left.key.localeCompare(right.key);
      return right.count - left.count;
    })
    .slice(0, limit);
}

function countBy(items, keyFn) {
  return items.reduce((counts, item) => {
    const key = keyFn(item);
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
}

function stringOrUnknown(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "unknown";
}

function localDateFromIso(value) {
  if (typeof value !== "string") return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return formatLocalDate(date);
}

function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

async function writeJsonAtomic(path, payload) {
  await writeTextAtomic(path, `${JSON.stringify(payload, null, 2)}\n`);
}

async function writeTextAtomic(path, text) {
  await mkdir(dirname(path), { recursive: true });
  const tmpPath = `${path}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(tmpPath, text, { encoding: "utf-8", mode: 0o600 });
  await rename(tmpPath, path);
}

main().catch((cause) => {
  console.error(cause instanceof Error ? cause.message : String(cause));
  process.exitCode = 1;
});
