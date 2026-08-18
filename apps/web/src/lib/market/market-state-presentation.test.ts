import { describe, expect, test } from "vitest";
import {
  formatAgeSeconds,
  reasonLabel,
  reasonSummary,
  statusLabel,
  technicalReasonCodes
} from "./market-state-presentation";

describe("market state presentation", () => {
  test("maps the four artifact states without creating another state model", () => {
    expect(["ready", "partial", "stale", "unavailable"].map(statusLabel)).toEqual([
      "正常",
      "一部取得",
      "期限切れ",
      "取得不能"
    ]);
  });

  test("humanizes known, prefixed and unknown reasons without hiding raw codes", () => {
    expect(reasonLabel("l1_older_than_120_seconds")).toContain("120秒以上");
    expect(reasonLabel("source_error_fetch_timeout")).toContain("fetch_timeout");
    expect(reasonLabel("future_reason")).toContain("future_reason");
    expect(technicalReasonCodes(["l1_missing", "l1_missing"], "source_error_timeout")).toEqual([
      "l1_missing",
      "source_error_timeout"
    ]);
    expect(reasonSummary(["l1_missing", "contains_non_ready_instruments"])).toContain(
      "L1データを取得できていません"
    );
  });

  test("renders a missing age as a missing timestamp rather than a number", () => {
    expect(formatAgeSeconds(null)).toBe("取得時刻なし");
    expect(formatAgeSeconds(12)).toBe("12秒");
  });
});
