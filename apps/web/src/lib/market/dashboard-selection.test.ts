import { describe, expect, it } from "vitest";
import { resolveDashboardSelection, validateDraftSymbol } from "./dashboard-selection";

describe("resolveDashboardSelection", () => {
  it("selects the first row only when no selection has been established", () => {
    const rows = [{ symbol: "BTCUSDT" }, { symbol: "ETHUSDT" }];

    expect(resolveDashboardSelection(null, rows)).toEqual({
      selectedSymbol: "BTCUSDT",
      row: rows[0],
      missing: false
    });
  });

  it("retains a missing selected symbol instead of silently choosing the first row", () => {
    const rows = [{ symbol: "ETHUSDT" }, { symbol: "SOLUSDT" }];

    expect(resolveDashboardSelection("BTCUSDT", rows)).toEqual({
      selectedSymbol: "BTCUSDT",
      row: null,
      missing: true
    });
  });
});

describe("validateDraftSymbol", () => {
  it("rejects an unconfirmed selection", () => {
    expect(
      validateDraftSymbol({ draftSymbol: null, displayedSymbol: null, availableSymbols: [] })
    ).toEqual({ reason: "selection-unconfirmed", ok: false });
  });

  it("rejects a draft whose originating symbol differs from the displayed symbol", () => {
    expect(
      validateDraftSymbol({
        draftSymbol: "BTCUSDT",
        displayedSymbol: "ETHUSDT",
        availableSymbols: ["BTCUSDT", "ETHUSDT"]
      })
    ).toEqual({ reason: "symbol-mismatch", ok: false });
  });

  it("rejects a draft whose symbol disappeared during a cold refresh", () => {
    expect(
      validateDraftSymbol({
        draftSymbol: "BTCUSDT",
        displayedSymbol: "BTCUSDT",
        availableSymbols: ["ETHUSDT"]
      })
    ).toEqual({ reason: "symbol-missing", ok: false });
  });

  it("allows only an established, matching, and still available symbol", () => {
    expect(
      validateDraftSymbol({
        draftSymbol: "BTCUSDT",
        displayedSymbol: "BTCUSDT",
        availableSymbols: ["BTCUSDT", "ETHUSDT"]
      })
    ).toEqual({ symbol: "BTCUSDT", ok: true });
  });
});
