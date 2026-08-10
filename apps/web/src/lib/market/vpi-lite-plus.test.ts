import { describe, expect, it } from "vitest";
import {
  buildVpiDiscoveryLane,
  parseVpiLitePlusItem,
  parseVpiLitePlusSummary,
  resolveVpiLitePlusRowItem,
  vpiDataQualityLabel,
  vpiFundingStateLabel,
  vpiOpenInterestStateLabel,
  vpiReasonLabel,
  vpiRiskLabel,
  vpiStateLabel
} from "./vpi-lite-plus";

const validItem = {
  symbol: "SOLUSDT",
  state: "EARLY_ACTIVITY",
  score: 48.5,
  reasonCodes: ["ABS_RETURN_UP", "TURNOVER_UP"],
  riskTagCodes: [],
  fundingState: "NORMAL",
  openInterestState: "AVAILABLE",
  dataQuality: "OK",
  dataAsOf: 1_780_000_000_000
};

describe("VPI-Lite+ payload guards", () => {
  it("accepts the closed V0 summary contract", () => {
    expect(
      parseVpiLitePlusSummary({
        schemaVersion: 1,
        mode: "lite_plus_v0",
        generatedAt: 1_780_000_060_000,
        benchmarks: [{ ...validItem, symbol: "BTCUSDT", state: "CALM" }],
        targets: [validItem]
      })
    ).toEqual({
      schemaVersion: 1,
      mode: "lite_plus_v0",
      generatedAt: 1_780_000_060_000,
      benchmarks: [{ ...validItem, symbol: "BTCUSDT", state: "CALM" }],
      targets: [validItem]
    });
  });

  it("rejects invalid top-level shapes and filters invalid symbol items", () => {
    expect(parseVpiLitePlusSummary(undefined)).toBeNull();
    expect(parseVpiLitePlusSummary({ ...validItem, schemaVersion: 1 })).toBeNull();
    expect(
      parseVpiLitePlusSummary({
        schemaVersion: 1,
        mode: "lite_plus_v0",
        generatedAt: 1,
        benchmarks: [{ ...validItem, score: Number.NaN }],
        targets: [validItem, { ...validItem, state: "BUY_NOW" }]
      })
    ).toEqual({
      schemaVersion: 1,
      mode: "lite_plus_v0",
      generatedAt: 1,
      benchmarks: [],
      targets: [validItem]
    });
  });

  it("rejects out-of-range scores, unknown enums, and malformed arrays", () => {
    expect(parseVpiLitePlusItem({ ...validItem, score: -0.1 })).toBeNull();
    expect(parseVpiLitePlusItem({ ...validItem, score: 100.1 })).toBeNull();
    expect(parseVpiLitePlusItem({ ...validItem, dataQuality: "MISSING" })).toBeNull();
    expect(parseVpiLitePlusItem({ ...validItem, fundingState: "HIGH" })).toBeNull();
    expect(parseVpiLitePlusItem({ ...validItem, reasonCodes: "TURNOVER_UP" })).toBeNull();
    expect(parseVpiLitePlusItem({ ...validItem, dataAsOf: Number.POSITIVE_INFINITY })).toBeNull();
  });

  it("accepts a row copy only when it matches the selected symbol and canonical summary item", () => {
    const summary = parseVpiLitePlusSummary({
      schemaVersion: 1,
      mode: "lite_plus_v0",
      generatedAt: 1_780_000_060_000,
      benchmarks: [],
      targets: [validItem]
    });
    expect(summary).not.toBeNull();
    if (!summary) throw new Error("valid VPI summary was rejected");

    expect(resolveVpiLitePlusRowItem(summary, "SOLUSDT", validItem)).toEqual(validItem);
    expect(resolveVpiLitePlusRowItem(summary, "ALTUSDT", validItem)).toBeNull();
    expect(resolveVpiLitePlusRowItem(summary, "SOLUSDT", { ...validItem, score: 49 })).toBeNull();
    expect(
      resolveVpiLitePlusRowItem(summary, "SOLUSDT", {
        ...validItem,
        reasonCodes: [...validItem.reasonCodes].reverse()
      })
    ).toBeNull();
  });
});

describe("VPI-Lite+ Japanese labels", () => {
  it("maps every V0 state without exposing raw enum labels", () => {
    expect([
      vpiStateLabel("CALM"),
      vpiStateLabel("EARLY_ACTIVITY"),
      vpiStateLabel("ACTIVE_MOVE"),
      vpiStateLabel("THIN_VOLATILITY"),
      vpiStateLabel("SINGLE_BAR_SUSPECT"),
      vpiStateLabel("DATA_INSUFFICIENT"),
      vpiStateLabel("DATA_STALE"),
      vpiStateLabel("UNKNOWN")
    ]).toEqual([
      "平常",
      "活動増加",
      "活発な変動",
      "薄商いの変動",
      "単発足への偏り",
      "データ不足",
      "データ遅延",
      "判定不能"
    ]);
  });

  it("maps reasons, risks, quality, funding, and OI availability", () => {
    expect(vpiReasonLabel("ABS_RETURN_UP")).toBe("値動きの活動増加");
    expect(vpiReasonLabel("TURNOVER_UP")).toBe("売買代金の活動増加");
    expect(vpiReasonLabel("RANGE_UP")).toBe("値幅の活動増加");
    expect(vpiRiskLabel("THIN_TURNOVER")).toBe("売買代金が薄い");
    expect(vpiRiskLabel("SINGLE_BAR_SUSPECT")).toBe("変動が1本へ偏っている");
    expect(vpiRiskLabel("FUNDING_OVERHEATED")).toBe("Fundingが高偏り");
    expect(vpiDataQualityLabel("INSUFFICIENT")).toBe("データ不足");
    expect(vpiFundingStateLabel("OVERHEATED")).toBe("高偏り");
    expect(vpiOpenInterestStateLabel("AVAILABLE")).toBe("取得あり");
  });
});

describe("VPI-Lite+ discovery lane", () => {
  it("classifies, sorts, limits, and reports explicit coverage", () => {
    const summary = parseVpiLitePlusSummary({
      schemaVersion: 1,
      mode: "lite_plus_v0",
      generatedAt: 1,
      benchmarks: [{ ...validItem, symbol: "BTCUSDT", state: "ACTIVE_MOVE", score: 100 }],
      targets: [
        { ...validItem, symbol: "EARLY1", state: "EARLY_ACTIVITY", score: 40 },
        { ...validItem, symbol: "ACTIVE1", state: "ACTIVE_MOVE", score: 80 },
        { ...validItem, symbol: "THIN1", state: "THIN_VOLATILITY", score: 70 },
        { ...validItem, symbol: "SINGLE1", state: "SINGLE_BAR_SUSPECT", score: 60 },
        { ...validItem, symbol: "CALM1", state: "CALM", score: 10 }
      ]
    });
    if (!summary) throw new Error("valid VPI summary was rejected");

    const lane = buildVpiDiscoveryLane(summary, 20);

    expect(lane.coverageLabel).toBe("VPI対象 5 / Watchlist 20銘柄");
    expect(lane.status).toBe("ready");
    expect(lane.activity.map((item) => item.symbol)).toEqual(["ACTIVE1", "EARLY1"]);
    expect(lane.caution.map((item) => item.symbol)).toEqual(["THIN1", "SINGLE1"]);
  });

  it("distinguishes no targets, no matching activity, and unavailable data", () => {
    const summary = (targets: unknown[]) =>
      parseVpiLitePlusSummary({
        schemaVersion: 1,
        mode: "lite_plus_v0",
        generatedAt: 1,
        benchmarks: [],
        targets
      });

    const none = summary([]);
    const calm = summary([{ ...validItem, state: "CALM" }]);
    const unavailable = summary([
      { ...validItem, state: "DATA_STALE", dataQuality: "STALE" }
    ]);
    if (!none || !calm || !unavailable) throw new Error("valid VPI summary was rejected");

    expect(buildVpiDiscoveryLane(none, 4).status).toBe("no-targets");
    expect(buildVpiDiscoveryLane(calm, 4).status).toBe("no-match");
    expect(buildVpiDiscoveryLane(unavailable, 4).status).toBe("unavailable");
  });
});
