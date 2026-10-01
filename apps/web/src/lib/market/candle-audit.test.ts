import { describe, expect, test } from "vitest";
import type { AuditMarkerBucket } from "$lib/generated/candle-audit-detail";
import { auditStatusLabel, displayAuditMarkers } from "./candle-audit";

describe("保存足照合のChart注記", () => {
  test("1分bucketを表示時間足へまとめ、件数と先頭詳細位置を保つ", () => {
    const buckets: AuditMarkerBucket[] = [
      { bucketAt: "2026-09-30T00:01:00Z", findingCount: 2,
        kinds: ["value_difference"], firstFindingOffset: 7 },
      { bucketAt: "2026-09-30T00:09:00Z", findingCount: 3,
        kinds: ["missing_bar"], firstFindingOffset: 2 },
      { bucketAt: "2026-09-30T00:16:00Z", findingCount: 1,
        kinds: ["return_difference"], firstFindingOffset: 12 }
    ];
    expect(displayAuditMarkers(buckets, "15m")).toEqual([
      { bucketAt: "2026-09-30T00:00:00.000Z", findingCount: 5, firstFindingOffset: 2 },
      { bucketAt: "2026-09-30T00:15:00.000Z", findingCount: 1, firstFindingOffset: 12 }
    ]);
    expect(displayAuditMarkers(buckets, "24h")).toEqual([
      { bucketAt: "2026-09-30T00:00:00.000Z", findingCount: 6, firstFindingOffset: 2 }
    ]);
  });
});

test("保存足の未実施・失敗・不足・差異・同一入力を別の表示にする", () => {
  type Entry = NonNullable<Parameters<typeof auditStatusLabel>[0]>;
  const entry = (execution: Entry["execution"], outcome: Entry["outcome"], same = false): Entry => ({
    execution, outcome, evidenceKind: "synthetic",
    inputs: {
      left: { fileSha256: "a" }, right: { fileSha256: same ? "a" : "b" }
    }
  }) as Entry;
  expect(auditStatusLabel(null, "not_run")).toContain("未照合");
  expect(auditStatusLabel(null, "unavailable")).toContain("取得不能");
  expect(auditStatusLabel(entry("failed", null), "available")).toContain("照合失敗");
  expect(auditStatusLabel(entry("completed", "incomplete"), "available")).toContain("一部未照合");
  expect(auditStatusLabel(entry("completed", "unverified"), "available")).toContain("照合不足");
  expect(auditStatusLabel(entry("completed", "differences"), "available")).toContain("差異あり");
  expect(auditStatusLabel(entry("completed", "match"), "available")).toContain("許容値内");
  expect(auditStatusLabel(entry("completed", "match", true), "available")).toContain("同一入力");
});
