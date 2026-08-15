import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { extname, relative, resolve } from "node:path";

const repoRoot = resolve(import.meta.dirname, "../..");

const ignoredDirectories = new Set([
  ".ai-work",
  ".codex",
  ".git",
  ".serena",
  ".svelte-kit",
  ".venv",
  "build",
  "coverage",
  "data",
  "dist",
  "node_modules",
  "out",
  "playwright-report",
  "test-results",
  "var"
]);

const sourceExtensions = new Set([
  ".cjs",
  ".css",
  ".env",
  ".example",
  ".html",
  ".js",
  ".json",
  ".mjs",
  ".py",
  ".sh",
  ".svelte",
  ".toml",
  ".ts",
  ".yaml",
  ".yml"
]);

const pathAllowlist = [
  {
    id: "documentation",
    reason: "Current docs and the active plan are updated after production code reaches the new boundary.",
    matches: (path) => path.endsWith(".md") || path.startsWith("mockups/")
  },
  {
    id: "tests-and-fixtures",
    reason: "Regression tests and fixtures may name the retired contract while proving removal or compatibility.",
    matches: (path) =>
      /(^|\/)(tests?|fixtures)(\/|$)/u.test(path) ||
      /\.(test|spec|e2e|performance|soak)\.[^.]+$/u.test(path) ||
      path === "apps/web/test-state-paths.ts"
  },
  {
    id: "retired-record-archive",
    reason: "Archive and restore verification must identify the retired record formats explicitly.",
    matches: (path) =>
      new Set([
        "scripts/maintenance/archive-retired-records.sh",
        "scripts/maintenance/verify-retired-records-archive.sh"
      ]).has(path)
  },
  {
    id: "state-v1-compatibility",
    reason: "State migration keeps explicit v1 readers while excluding retired paths from a v2 active target.",
    matches: (path) =>
      new Set([
        "scripts/maintenance/migrate-state-dir.sh",
        "scripts/maintenance/verify-state-dir.sh"
      ]).has(path)
  }
];

const identifierAllowlist = [
  {
    id: "past-note-monitoring-annotation",
    reason: "Past Note remains a monitoring annotation and is not a trade record.",
    pattern: /\bPastNotes?\b|\bpastNotes?\b|past-notes?|Past Note/gu
  }
];

const rulePathAllowlist = [];

const forbiddenIdentifiers = [
  {
    id: "trade-memo",
    reason: "Trade Memo domain, client, component, route, and state identifiers are retired.",
    pattern: /\bTradeMemo[A-Za-z0-9_]*\b|\btradeMemos?\b|trade-memos?/gu
  },
  {
    id: "attack-ticket",
    reason: "Attack Ticket domain, client, component, route, and state identifiers are retired.",
    pattern: /\bAttackTicket[A-Za-z0-9_]*\b|\battackTickets?\b|attack-tickets?/gu
  },
  {
    id: "weekly-review",
    reason: "Weekly Review API, calculation, UI, and export identifiers are retired.",
    pattern: /\bWeeklyReview[A-Za-z0-9_]*\b|\bweeklyReview[A-Za-z0-9_]*\b|weekly-review/gu
  },
  {
    id: "deal-check",
    reason: "Deal Check calculations and UI are outside the monitoring-only product boundary.",
    pattern: /\bDealCheck[A-Za-z0-9_]*\b|\bdealCheck[A-Za-z0-9_]*\b|deal-check/gu
  },
  {
    id: "pre-trade-check",
    reason: "Pre-Trade Check and ticket snapshot identifiers are retired.",
    pattern: /\bPreTrade[A-Za-z0-9_]*\b|\bpreTrade[A-Za-z0-9_]*\b|pre-trade/gu
  },
  {
    id: "position-size-pressure",
    reason: "Position Size Pressure calculations and UI are retired.",
    pattern: /\bPositionSizePressure[A-Za-z0-9_]*\b|\bpositionSizePressure[A-Za-z0-9_]*\b|position-size-pressure/gu
  },
  {
    id: "quick-or-full-skip",
    reason: "Quick SKIP and Full SKIP are retired trade-decision record modes.",
    pattern: /Quick[ _-]?SKIP|Full[ _-]?SKIP|quickSkip|fullSkip/gu
  },
  {
    id: "trade-skip-decision-token",
    reason: "Standalone TRADE/SKIP decision tokens must not remain in production record code.",
    pattern: /TRADE\s*\/\s*SKIP|(["'`])(?:TRADE|SKIP)\1/gu
  },
  {
    id: "retired-record-copy",
    reason: "User-facing trade/skip record copy must not remain in production UI.",
    pattern: /簡易見送り記録|詳細見送り記録|見送り記録/gu
  },
  {
    id: "retired-runtime-env",
    reason: "Runtime configuration must not expose Trade Memo or Attack Ticket state paths.",
    pattern:
      /\b(?:PREP_WATCHDECK_|WATCHDECK_)?(?:TRADE_MEMOS|ATTACK_TICKETS)_DIR\b|\b(?:TRADE_MEMOS|ATTACK_TICKETS)_DIR\b/gu
  },
  {
    id: "retired-usage-event",
    reason: "Monitoring-only runtime code must not emit or actively summarize retired record events.",
    pattern:
      /\b(?:quick_skip_saved|attack_ticket_saved|trade_memo_saved|weekly_review_opened|record_save_failed)\b/gu
  }
];

const forbiddenRoutePaths = [
  "apps/web/src/routes/api/attack-tickets/+server.ts",
  "apps/web/src/routes/api/trade-memos/+server.ts",
  "apps/web/src/routes/api/weekly-review/+server.ts"
];

const productionFiles = collectProductionFiles();
const violations = auditProductionFiles(productionFiles);

describe("monitoring-only production boundary", () => {
  test("uses narrow, named path and identifier allowlists", () => {
    expect(pathAllowlist.map(({ id }) => id)).toEqual([
      "documentation",
      "tests-and-fixtures",
      "retired-record-archive",
      "state-v1-compatibility"
    ]);
    expect(identifierAllowlist.map(({ id }) => id)).toEqual([
      "past-note-monitoring-annotation"
    ]);
    expect(rulePathAllowlist.map(({ id }) => id)).toEqual([]);
  });

  test("retired API route files do not exist", () => {
    const existing = forbiddenRoutePaths.filter((path) => existsSync(resolve(repoRoot, path)));
    if (existing.length > 0) {
      throw new Error(
        [
          "[retired-api-route] Retired route files still exist:",
          ...existing.map((path) => `- ${path}`)
        ].join("\n")
      );
    }
  });

  for (const rule of forbiddenIdentifiers) {
    test(`${rule.id}: ${rule.reason}`, () => {
      const matching = violations.filter((violation) => violation.ruleId === rule.id);
      if (matching.length > 0) {
        throw new Error(formatViolations(rule, matching));
      }
    });
  }
});

function collectProductionFiles() {
  const files = [];
  walk(repoRoot, files);
  return files.sort();
}

function walk(directory, output) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue;
    const absolutePath = resolve(directory, entry.name);
    if (entry.isDirectory()) {
      walk(absolutePath, output);
      continue;
    }
    if (!entry.isFile()) continue;

    const path = relative(repoRoot, absolutePath).replaceAll("\\", "/");
    if (!isSourceFile(path) || allowedPath(path)) continue;
    output.push(path);
  }
}

function isSourceFile(path) {
  return sourceExtensions.has(extname(path)) || path === ".env.example";
}

function allowedPath(path) {
  return pathAllowlist.some(({ matches }) => matches(path));
}

function auditProductionFiles(paths) {
  const byRuleAndPath = new Map();

  for (const path of paths) {
    const content = maskAllowedIdentifiers(readFileSync(resolve(repoRoot, path), "utf8"));
    const searchable = `${path}\n${content}`;

    for (const rule of forbiddenIdentifiers) {
      if (allowedRulePath(rule.id, path)) continue;
      for (const match of searchable.matchAll(rule.pattern)) {
        const key = `${rule.id}\u0000${path}`;
        const existing = byRuleAndPath.get(key);
        if (existing) {
          existing.count += 1;
          continue;
        }

        const contentOffset = path.length + 1;
        const contentIndex = Math.max(0, (match.index ?? 0) - contentOffset);
        byRuleAndPath.set(key, {
          ruleId: rule.id,
          path,
          count: 1,
          line: (match.index ?? 0) < contentOffset ? "path" : lineNumber(content, contentIndex),
          sample:
            (match.index ?? 0) < contentOffset
              ? match[0]
              : lineAt(content, contentIndex).trim().slice(0, 180)
        });
      }
    }
  }

  return [...byRuleAndPath.values()].sort((left, right) =>
    `${left.ruleId}\u0000${left.path}`.localeCompare(`${right.ruleId}\u0000${right.path}`)
  );
}

function allowedRulePath(ruleId, path) {
  return rulePathAllowlist.some(
    ({ ruleId: allowedRuleId, paths }) => allowedRuleId === ruleId && paths.has(path)
  );
}

function maskAllowedIdentifiers(content) {
  let masked = content;
  for (const { pattern } of identifierAllowlist) {
    masked = masked.replace(pattern, (value) => value.replace(/[^\n]/gu, " "));
  }
  return masked;
}

function lineNumber(content, index) {
  return content.slice(0, index).split("\n").length;
}

function lineAt(content, index) {
  const start = content.lastIndexOf("\n", Math.max(0, index - 1)) + 1;
  const end = content.indexOf("\n", index);
  return content.slice(start, end === -1 ? content.length : end);
}

function formatViolations(rule, matching) {
  return [
    `[${rule.id}] ${rule.reason}`,
    ...matching.map(
      ({ path, line, count, sample }) =>
        `- ${path}:${line} (${count} match${count === 1 ? "" : "es"}) first=${JSON.stringify(sample)}`
    )
  ].join("\n");
}
