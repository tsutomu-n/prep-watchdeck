import { describe, expect, it } from "vitest";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import {
  buildSmartRankState,
  canRunSmartRank,
  normalizeSmartRankTargetLimit,
  smartRankCooldownRemainingSeconds
} from "./smart-rank";

function row(symbol: string, attentionScore: number, overrides: Partial<ScannerRowDTO> = {}): ScannerRowDTO {
  return {
    symbol,
    ts: 0,
    category: "WATCH",
    label: "VOLUME_CONFIRMED_UP",
    attentionScore,
    changePctByTf: {},
    turnoverUsdtByTf: {},
    dataQuality: "OK",
    reasonCodes: [],
    riskTagCodes: [],
    ...overrides
  };
}

const rawSortState = {
  sortKey: "changePct" as const,
  direction: "desc" as const
};

describe("smart rank", () => {
  it("targets only the current raw sort top N rows", () => {
    const state = buildSmartRankState({
      rows: [row("A", 10), row("B", 90), row("C", 80)],
      snapshotRunId: "run-1",
      timeframe: "1h",
      rawSortState,
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 2,
      nowMs: 1000,
      newId: () => "smart-1"
    });

    expect(state.base).toMatchObject({
      smartRankRunId: "smart-1",
      baseSnapshotRunId: "run-1",
      timeframe: "1h",
      sortKey: "changePct",
      sortDirection: "desc",
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 2,
      targetSymbols: ["A", "B"]
    });
    expect(state.rows.map((item) => item.row.symbol).sort()).toEqual(["A", "B"]);
  });

  it("uses a 30 second cooldown after a run", () => {
    const state = buildSmartRankState({
      rows: [row("A", 10)],
      snapshotRunId: "run-1",
      timeframe: "15m",
      rawSortState,
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 20,
      nowMs: 1000
    });

    expect(canRunSmartRank({ nowMs: 30_999, state, availableRows: 1 })).toBe(false);
    expect(smartRankCooldownRemainingSeconds(30_999, state)).toBe(1);
    expect(canRunSmartRank({ nowMs: 31_000, state, availableRows: 1 })).toBe(true);
  });

  it("clamps target limit and rejects empty rows", () => {
    expect(normalizeSmartRankTargetLimit("999")).toBe(50);
    expect(normalizeSmartRankTargetLimit("0")).toBe(1);
    expect(normalizeSmartRankTargetLimit("bad")).toBe(20);
    expect(canRunSmartRank({ nowMs: 0, state: null, availableRows: 0 })).toBe(false);
  });

  it("keeps smart score ties stable by source rank", () => {
    const state = buildSmartRankState({
      rows: [row("FIRST", 50), row("SECOND", 50)],
      snapshotRunId: "run-1",
      timeframe: "15m",
      rawSortState,
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 2,
      nowMs: 1000
    });

    expect(state.rows.map((item) => item.row.symbol)).toEqual(["FIRST", "SECOND"]);
  });

  it("does not boost smart score from warning count", () => {
    const state = buildSmartRankState({
      rows: [
        row("SAFE", 50),
        row("WARN", 49, { riskTagCodes: ["A", "B", "C", "D"] })
      ],
      snapshotRunId: "run-1",
      timeframe: "15m",
      rawSortState,
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 2,
      nowMs: 1000
    });

    expect(state.rows.map((item) => [item.row.symbol, item.smartScore, item.warningCount])).toEqual([
      ["SAFE", 50, 0],
      ["WARN", 49, 4]
    ]);
  });

  it("keeps data quality as a penalty instead of a warning boost", () => {
    const state = buildSmartRankState({
      rows: [
        row("OK", 50),
        row("STALE", 60, { dataQuality: "STALE", riskTagCodes: ["A", "B", "C"] })
      ],
      snapshotRunId: "run-1",
      timeframe: "15m",
      rawSortState,
      categoryFilter: "ALL",
      viewFilter: "standard",
      targetLimit: 2,
      nowMs: 1000
    });

    expect(state.rows.map((item) => [item.row.symbol, item.smartScore, item.qualityPenalty])).toEqual([
      ["OK", 50, 0],
      ["STALE", 48, 12]
    ]);
  });
});
