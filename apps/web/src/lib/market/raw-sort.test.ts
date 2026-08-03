import { describe, expect, it } from "vitest";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import type { DashboardRawSortState } from "./dashboard-filters";
import { getRawSortValue, sortRowsByRawSort } from "./raw-sort";

function row(symbol: string, overrides: Partial<ScannerRowDTO> = {}): ScannerRowDTO {
  return {
    symbol,
    ts: 0,
    category: "WATCH",
    label: "VOLUME_CONFIRMED_UP",
    attentionScore: 10,
    changePctByTf: {},
    turnoverUsdtByTf: {},
    dataQuality: "OK",
    reasonCodes: [],
    riskTagCodes: [],
    ...overrides
  };
}

function state(overrides: Partial<DashboardRawSortState> = {}): DashboardRawSortState {
  return {
    sortKey: "changePct",
    direction: "desc",
    ...overrides
  };
}

describe("raw sort", () => {
  it("sorts price change descending and ascending", () => {
    const rows = [
      row("FLAT", { changePctByTf: { "15m": 0.1 } }),
      row("UP", { changePctByTf: { "15m": 3.2 } }),
      row("DOWN", { changePctByTf: { "15m": -2.4 } })
    ];

    expect(sortRowsByRawSort(rows, state(), "15m").map((item) => item.symbol)).toEqual([
      "UP",
      "FLAT",
      "DOWN"
    ]);
    expect(sortRowsByRawSort(rows, state({ direction: "asc" }), "15m").map((item) => item.symbol)).toEqual([
      "DOWN",
      "FLAT",
      "UP"
    ]);
  });

  it("sorts turnover and volume ratio by selected timeframe", () => {
    const rows = [
      row("LOW", {
        turnoverUsdtByTf: { "1h": 10_000 },
        volumeRatioByTf: { "1h": 1.2 }
      }),
      row("HIGH", {
        turnoverUsdtByTf: { "1h": 80_000 },
        volumeRatioByTf: { "1h": 3.4 }
      })
    ];

    expect(
      sortRowsByRawSort(rows, state({ sortKey: "turnoverUsdt" }), "1h").map(
        (item) => item.symbol
      )
    ).toEqual(["HIGH", "LOW"]);
    expect(
      sortRowsByRawSort(rows, state({ sortKey: "volumeRatio" }), "1h").map(
        (item) => item.symbol
      )
    ).toEqual(["HIGH", "LOW"]);
  });

  it("sorts attention score, risk tag count, and data quality", () => {
    const rows = [
      row("LOW_SCORE", { attentionScore: 12, riskTagCodes: [], dataQuality: "MISSING" }),
      row("HIGH_SCORE", { attentionScore: 88, riskTagCodes: ["A", "B"], dataQuality: "OK" }),
      row("MID_SCORE", { attentionScore: 40, riskTagCodes: ["A"], dataQuality: "PARTIAL" })
    ];

    expect(sortRowsByRawSort(rows, state({ sortKey: "attentionScore" }), "15m").map((item) => item.symbol)).toEqual([
      "HIGH_SCORE",
      "MID_SCORE",
      "LOW_SCORE"
    ]);
    expect(sortRowsByRawSort(rows, state({ sortKey: "riskTagCount" }), "15m").map((item) => item.symbol)).toEqual([
      "HIGH_SCORE",
      "MID_SCORE",
      "LOW_SCORE"
    ]);
    expect(sortRowsByRawSort(rows, state({ sortKey: "dataQuality" }), "15m").map((item) => item.symbol)).toEqual([
      "HIGH_SCORE",
      "MID_SCORE",
      "LOW_SCORE"
    ]);
  });

  it("keeps missing and non-finite values at the end for both directions", () => {
    const rows = [
      row("MISSING", { changePctByTf: {} }),
      row("FINITE", { changePctByTf: { "74h": 4.2 } }),
      row("NAN", { changePctByTf: { "74h": Number.NaN } })
    ];

    expect(sortRowsByRawSort(rows, state(), "74h").map((item) => item.symbol)).toEqual([
      "FINITE",
      "MISSING",
      "NAN"
    ]);
    expect(
      sortRowsByRawSort(rows, state({ direction: "asc" }), "74h").map((item) => item.symbol)
    ).toEqual(["FINITE", "MISSING", "NAN"]);
  });

  it("keeps equal values stable", () => {
    const rows = [
      row("FIRST", { changePctByTf: { "15m": 1 } }),
      row("SECOND", { changePctByTf: { "15m": 1 } }),
      row("THIRD", { changePctByTf: { "15m": 1 } })
    ];

    expect(sortRowsByRawSort(rows, state(), "15m").map((item) => item.symbol)).toEqual([
      "FIRST",
      "SECOND",
      "THIRD"
    ]);
  });

  it("returns null for missing 74h values", () => {
    expect(getRawSortValue(row("ALT", { changePctByTf: { "15m": 1 } }), state(), "74h")).toBeNull();
  });
});
