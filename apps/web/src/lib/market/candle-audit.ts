import type { AuditIndexEntry } from "$lib/generated/candle-audit-index";
import type { AuditMarkerBucket, AuditFinding } from "$lib/generated/candle-audit-detail";
import { CHART_TIMEFRAME_SECONDS, type Timeframe } from "$lib/market/chart-history";

export function auditTargetKey(id: string, version: number): string {
  return `${id}\u0000${version}`;
}

export function auditStatusLabel(entry: Pick<AuditIndexEntry, "execution" | "outcome" | "inputs" | "evidenceKind"> | null, state: "loading" | "available" | "not_run" | "unavailable"): string {
  if (state === "loading") return "保存足 読込中";
  if (state === "unavailable") return "保存足 取得不能";
  if (!entry) return "保存足 未照合";
  const suffix = entry.evidenceKind === "synthetic" ? " · テスト" : "";
  if (entry.execution !== "completed") return `保存足 照合失敗${suffix}`;
  if (entry.outcome === "incomplete") return `保存足 一部未照合${suffix}`;
  if (entry.outcome === "unverified") return `保存足 照合不足${suffix}`;
  if (entry.outcome === "differences") return `保存足 差異あり${suffix}`;
  if (entry.outcome === "match" && entry.inputs.left.fileSha256 !== null &&
      entry.inputs.left.fileSha256 === entry.inputs.right.fileSha256) {
    return `保存足 同一入力${suffix}`;
  }
  return `保存足 許容値内${suffix}`;
}

export type DisplayAuditMarker = {
  bucketAt: string;
  findingCount: number;
  firstFindingOffset: number;
};

export function displayAuditMarkers(
  buckets: AuditMarkerBucket[], timeframe: Timeframe
): DisplayAuditMarker[] {
  const duration = CHART_TIMEFRAME_SECONDS[timeframe] * 1000;
  const grouped = new Map<number, DisplayAuditMarker>();
  for (const bucket of buckets) {
    const source = Date.parse(bucket.bucketAt);
    if (!Number.isFinite(source)) continue;
    const start = Math.floor(source / duration) * duration;
    const current = grouped.get(start);
    if (current) {
      current.findingCount += bucket.findingCount;
      current.firstFindingOffset = Math.min(current.firstFindingOffset, bucket.firstFindingOffset);
    } else {
      grouped.set(start, {
        bucketAt: new Date(start).toISOString(),
        findingCount: bucket.findingCount,
        firstFindingOffset: bucket.firstFindingOffset
      });
    }
  }
  return [...grouped.values()].sort((a, b) => a.bucketAt.localeCompare(b.bucketAt));
}

export function findingReasonLabel(finding: AuditFinding): string {
  const labels: Record<AuditFinding["reasonCode"], string> = {
    value_tolerance_exceeded: "許容差を超える値の差",
    return_tolerance_exceeded: "5分対数リターンの差",
    missing_bucket: "保存足がありません",
    duplicate_bucket: "同じ時刻の足が重複",
    record_version_mismatch: "契約版が一致しません",
    record_is_not_final: "足が確定していません",
    observed_before_close: "区間終了前の観測",
    unavailable_at_as_of: "評価基準時刻では未取得",
    invalid_timestamp: "時刻が不正",
    invalid_numeric: "数値が不正",
    invalid_ohlc: "OHLC関係が不正",
    invalid_row: "入力行が不正",
    missing_requested_value: "比較値が欠けています",
    missing_return_endpoint: "リターン計算に必要な終値がありません"
  };
  return labels[finding.reasonCode];
}
