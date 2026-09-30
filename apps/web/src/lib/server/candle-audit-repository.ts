import { lstat } from "node:fs/promises";
import { join, dirname } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import indexSchema from "../../../../../schemas/candle-audit-index.schema.json";
import reportSchema from "../../../../../schemas/candle-audit-report.schema.json";
import detailSchema from "../../../../../schemas/candle-audit-detail.schema.json";
import type { AuditIndex } from "$lib/generated/candle-audit-index";
import type { AuditReport, AuditFinding } from "$lib/generated/candle-audit-report";
import type { AuditDetailPage } from "$lib/generated/candle-audit-detail";
import { readBoundedStateJson, StateFileError } from "./bounded-state-json";
import { resolveMarketStatePaths } from "./market-state-paths";

const ajv = new Ajv2020({ strict: false });
ajv.addFormat("date-time", { type: "string", validate: utcTime });
const validateIndex = ajv.compile(indexSchema);
const validateReport = ajv.compile(reportSchema);
const validateDetail = ajv.compile(detailSchema);
const RUN_ID = /^[0-9a-f]{32}$/;
const MINUTE = 60_000;

function utcTime(value: string): boolean {
  return /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}

function windowBars(window: { start: string; end: string; dataAsOf: string }): number {
  const start = Date.parse(window.start);
  const end = Date.parse(window.end);
  const asOf = Date.parse(window.dataAsOf);
  const bars = (end - start) / MINUTE;
  if (!Number.isInteger(bars) || bars <= 5 || bars > 7 * 24 * 60 ||
      start % MINUTE !== 0 || end % MINUTE !== 0 || asOf < end) {
    throw new Error("audit window invalid");
  }
  return bars;
}

function validateHeader(entry: {
  startedAt: string; checkedAt: string; window: { start: string; end: string; dataAsOf: string };
  execution: string; outcome: string | null; errorCode: string | null;
  summary: { expectedBars: number; expectedReturnPairs: number; returnPairs: number;
    commonValidBars: number; comparedPriceValues: number; totalFindings: number } | null;
}) {
  const bars = windowBars(entry.window);
  if (Date.parse(entry.checkedAt) < Date.parse(entry.startedAt) ||
      Date.parse(entry.window.dataAsOf) > Date.parse(entry.startedAt) ||
      (entry.execution === "completed") !== (entry.outcome !== null && entry.errorCode === null) ||
      (entry.execution !== "completed" && entry.summary !== null) ||
      (entry.summary !== null && (
        entry.summary.expectedBars !== bars ||
        entry.summary.expectedReturnPairs !== bars - 5 ||
        entry.summary.returnPairs > bars - 5 ||
        entry.summary.commonValidBars > bars ||
        entry.summary.comparedPriceValues !== entry.summary.commonValidBars * 4
      ))) {
    throw new Error("audit header inconsistent");
  }
}

export async function readCandleAuditIndex(
  path = resolveMarketStatePaths().candleAuditIndexPath
): Promise<AuditIndex> {
  const payload = await readBoundedStateJson(path, 1024 * 1024);
  if (!validateIndex(payload)) throw new Error("audit index schema invalid");
  const index = payload as unknown as AuditIndex;
  const seen = new Set<string>();
  let previous = "";
  for (const entry of index.entries) {
    validateHeader(entry);
    const key = `${entry.target.venueInstrumentId}\u0000${String(entry.target.venueInstrumentVersionId).padStart(20, "0")}`;
    if (key <= previous || seen.has(key)) throw new Error("audit index target order invalid");
    previous = key;
    seen.add(key);
  }
  return index;
}

function findingKey(finding: AuditFinding): string {
  return [finding.bucketAt ?? "\uffff", finding.kind, finding.field ?? "",
    finding.side ?? "", String(finding.rowNumber ?? 0).padStart(8, "0")].join("\u0000");
}

function validateFullReport(report: AuditReport, runId: string): void {
  validateHeader(report);
  if (report.runId !== runId ||
      (report.series !== null && (
        `${report.series.venue}:${report.series.sourceSymbol}` !== report.target.venueInstrumentId ||
        report.series.venueInstrumentVersionId !== report.target.venueInstrumentVersionId
      )) ||
      (report.execution === "completed" && (report.series === null || report.summary === null)) ||
      (report.execution !== "completed" && report.findings.length !== 0) ||
      (report.summary !== null && report.summary.totalFindings !== report.findings.length)) {
    throw new Error("audit report identity inconsistent");
  }
  let previous = "";
  for (let index = 0; index < report.findings.length; index++) {
    const finding = report.findings[index];
    if (finding.id !== `f${String(index + 1).padStart(6, "0")}`) {
      throw new Error("audit finding ID inconsistent");
    }
    const key = findingKey(finding);
    if (key < previous) throw new Error("audit findings unsorted");
    previous = key;
  }
}

async function validateRunParents(runsDir: string, runId: string): Promise<void> {
  for (const path of [dirname(runsDir), runsDir, join(runsDir, runId)]) {
    try {
      const info = await lstat(path);
      if (!info.isDirectory() || info.isSymbolicLink()) throw new StateFileError("unavailable");
    } catch (cause) {
      if (cause instanceof StateFileError) throw cause;
      if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
        throw new StateFileError("missing");
      }
      throw new StateFileError("unavailable");
    }
  }
}

export async function readCandleAuditDetail(
  runId: string,
  { offset = 0, limit = 200, runsDir = resolveMarketStatePaths().candleAuditRunsDir }:
    { offset?: number; limit?: number; runsDir?: string } = {}
): Promise<AuditDetailPage> {
  if (!RUN_ID.test(runId) || !Number.isSafeInteger(offset) || offset < 0 ||
      !Number.isSafeInteger(limit) || limit < 1 || limit > 200) {
    throw new Error("audit_invalid_request");
  }
  await validateRunParents(runsDir, runId);
  const payload = await readBoundedStateJson(join(runsDir, runId, "report.json"), 32 * 1024 * 1024);
  if (!validateReport(payload)) throw new Error("audit report schema invalid");
  const report = payload as unknown as AuditReport;
  validateFullReport(report, runId);
  const grouped = new Map<string, { count: number; kinds: Set<AuditFinding["kind"]>; first: number }>();
  const start = Date.parse(report.window.start);
  const end = Date.parse(report.window.end);
  for (let index = 0; index < report.findings.length; index++) {
    const finding = report.findings[index];
    const bucket = finding.bucketAt === null ? NaN : Date.parse(finding.bucketAt);
    if (!Number.isFinite(bucket) || bucket < start || bucket >= end || bucket % MINUTE !== 0) continue;
    const current = grouped.get(finding.bucketAt!) ?? { count: 0, kinds: new Set(), first: index };
    current.count++;
    current.kinds.add(finding.kind);
    grouped.set(finding.bucketAt!, current);
  }
  const markerBuckets = [...grouped.entries()].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
    .map(([bucketAt, value]) => ({ bucketAt, findingCount: value.count,
      kinds: [...value.kinds].sort(), firstFindingOffset: value.first }));
  const { findings: _all, ...header } = report;
  const result = {
    schemaVersion: 1,
    report: header,
    totalFindings: report.findings.length,
    offset,
    limit,
    findings: report.findings.slice(offset, offset + limit),
    hasMore: offset + limit < report.findings.length,
    markerBuckets
  };
  if (!validateDetail(result)) throw new Error("audit detail schema invalid");
  return result as AuditDetailPage;
}
