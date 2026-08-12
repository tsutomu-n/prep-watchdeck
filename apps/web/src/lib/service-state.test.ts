import { describe, expect, it } from "vitest";
import { dataSourceLabel, snapshotStatusLabel, templateLabel } from "./market/labels";
import { formatLag, serviceStateLabel, summarizeServiceState } from "./service-state";

describe("service state helpers", () => {
  it("summarizes fresh running service state as backfilling", () => {
    expect(
      summarizeServiceState(
        {
          generatedAtMs: 1_781_000_000_000,
          dataAsOfMs: 1_780_999_980_000,
          streamSymbols: 666,
          streamShards: 28,
          backfill: {
            status: "running",
            completedSymbols: 120,
            targetSymbols: 666
          }
        },
        1_781_000_030_000
      )
    ).toMatchObject({
      status: "backfilling",
      label: "Service 補完中",
      dataLagSeconds: 50,
      stateLagSeconds: 30,
      streamSymbols: 666,
      streamShards: 28,
      backfillText: "120/666"
    });
  });

  it("marks stale state when service or data timestamps are old", () => {
    expect(
      summarizeServiceState(
        {
          generatedAtMs: 1_781_000_000_000,
          dataAsOfMs: 1_781_000_000_000
        },
        1_781_000_200_000
      ).status
    ).toBe("stale");
  });

  it("ignores legacy deep backfill progress", () => {
    const legacyState = {
      generatedAtMs: 1_781_000_000_000,
      dataAsOfMs: 1_780_999_980_000,
      deepBackfill: {
        status: "running",
        completedSymbols: 120,
        targetSymbols: 666
      }
    };

    expect(
      summarizeServiceState(legacyState, 1_781_000_030_000)
    ).toMatchObject({ status: "ok", backfillText: "補完なし" });
  });

  it("keeps labels and lag formatting stable", () => {
    expect(serviceStateLabel("missing")).toBe("Service 状態なし");
    expect(serviceStateLabel("unreadable")).toBe("Service 状態エラー");
    expect(formatLag(45)).toBe("45秒前");
    expect(formatLag(125)).toBe("2分前");
    expect(formatLag(null)).toBe("-");
  });

  it("keeps source and service status labels stable for the runtime live regions", () => {
    expect(serviceStateLabel("backfilling")).toBe("Service 補完中");
    expect(snapshotStatusLabel("STALE")).toBe("古い");
    expect(dataSourceLabel("fixture")).toBe("検証データ");
    expect(templateLabel("basic")).toBe("基本");
  });
});
