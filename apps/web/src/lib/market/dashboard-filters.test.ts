import { describe, expect, it } from "vitest";
import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import {
  dashboardCategoryFilters,
  dashboardRawSortDirections,
  dashboardRawSortKeys,
  dashboardRankingMetrics,
  dashboardRankingTimeframes,
  dashboardViewModes,
  isDashboardCategoryFilter,
  isDashboardRankingTimeframe,
  isDashboardRawSortDirection,
  isDashboardRawSortKey,
  isDashboardViewMode,
  matchesDashboardView,
  normalizeDashboardViewSettings,
  defaultDashboardViewSettings,
  type DashboardViewSettings
} from "./dashboard-filters";

function row(overrides: Partial<ScannerRowDTO> = {}): ScannerRowDTO {
  return {
    symbol: "ALTUSDT",
    ts: 0,
    category: "WATCH",
    label: "VOLUME_CONFIRMED_UP",
    attentionScore: 10,
    changePctByTf: { "15m": 0 },
    turnoverUsdtByTf: { "15m": 0 },
    dataQuality: "OK",
    reasonCodes: [],
    riskTagCodes: [],
    ...overrides
  };
}

describe("dashboard filters", () => {
  it("keeps dashboard filter, timeframe, metric, and view labels stable", () => {
    expect(dashboardCategoryFilters).toEqual(["ALL", "WATCH", "CAUTION", "NO_TRADE", "LOW_PRIORITY"]);
    expect(dashboardRankingTimeframes).toEqual(["5m", "15m", "1h", "4h", "24h", "74h"]);
    expect(dashboardRankingMetrics).toEqual([
      ["上昇順", "changeUp"],
      ["下落順", "changeDown"],
      ["売買代金", "turnoverTop"],
      ["15分出来高倍率", "volumeUp"]
    ]);
    expect(dashboardRawSortKeys).toEqual([
      { id: "changePct", label: "価格変化" },
      { id: "turnoverUsdt", label: "売買代金" },
      { id: "volumeRatio", label: "15分出来高倍率" },
      { id: "attentionScore", label: "注目度" },
      { id: "riskTagCount", label: "警戒数" },
      { id: "dataQuality", label: "データ品質" }
    ]);
    expect(dashboardRawSortDirections).toEqual([
      { id: "desc", label: "大きい順" },
      { id: "asc", label: "小さい順" }
    ]);
    expect(dashboardViewModes).toEqual([
      { id: "standard", label: "標準" },
      { id: "watch", label: "注視のみ" },
      { id: "surge", label: "急騰" },
      { id: "drop", label: "急落" },
      { id: "turnover", label: "高売買代金" },
      { id: "quality", label: "低品質除外" }
    ]);
  });

  it("validates category and view ids", () => {
    expect(isDashboardCategoryFilter("WATCH")).toBe(true);
    expect(isDashboardCategoryFilter("BAD")).toBe(false);
    expect(isDashboardViewMode("turnover")).toBe(true);
    expect(isDashboardViewMode("BAD")).toBe(false);
    expect(isDashboardRankingTimeframe("74h")).toBe(true);
    expect(isDashboardRankingTimeframe("72h")).toBe(false);
    expect(isDashboardRawSortKey("volumeRatio")).toBe(true);
    expect(isDashboardRawSortKey("BAD")).toBe(false);
    expect(isDashboardRawSortDirection("asc")).toBe(true);
    expect(isDashboardRawSortDirection("BAD")).toBe(false);
  });

  it("matches standard category, watch, and quality views", () => {
    expect(
      matchesDashboardView(row({ category: "CAUTION" }), {
        activeCategory: "CAUTION",
        activeView: "standard",
        selectedTimeframe: "15m"
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ category: "LOW_PRIORITY" }), {
        activeCategory: "CAUTION",
        activeView: "standard",
        selectedTimeframe: "15m"
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ category: "WATCH" }), {
        activeCategory: "ALL",
        activeView: "watch",
        selectedTimeframe: "15m"
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ category: "WATCH", dataQuality: "PARTIAL" }), {
        activeCategory: "ALL",
        activeView: "quality",
        selectedTimeframe: "15m"
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ category: "NO_TRADE", dataQuality: "OK" }), {
        activeCategory: "ALL",
        activeView: "quality",
        selectedTimeframe: "15m"
      })
    ).toBe(false);
  });

  it("matches surge, drop, and turnover thresholds while excluding no-trade rows", () => {
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": 2 } }), {
        activeCategory: "ALL",
        activeView: "surge",
        selectedTimeframe: "15m"
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": -2 } }), {
        activeCategory: "ALL",
        activeView: "drop",
        selectedTimeframe: "15m"
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ turnoverUsdtByTf: { "15m": 50_000 } }), {
        activeCategory: "ALL",
        activeView: "turnover",
        selectedTimeframe: "15m"
      })
    ).toBe(true);
    expect(
      matchesDashboardView(
        row({
          category: "NO_TRADE",
          changePctByTf: { "15m": 20 },
          turnoverUsdtByTf: { "15m": 1_000_000 }
        }),
        {
          activeCategory: "ALL",
          activeView: "surge",
          selectedTimeframe: "15m"
        }
      )
    ).toBe(false);
  });

  it("keeps the fixed dashboard behavior through default view settings", () => {
    const settings = defaultDashboardViewSettings;
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": 1.9 } }), {
        activeCategory: "ALL",
        activeView: "surge",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": 2 } }), {
        activeCategory: "ALL",
        activeView: "surge",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ turnoverUsdtByTf: { "4h": 299_999 } }), {
        activeCategory: "ALL",
        activeView: "turnover",
        selectedTimeframe: "4h",
        settings
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ turnoverUsdtByTf: { "4h": 300_000 } }), {
        activeCategory: "ALL",
        activeView: "turnover",
        selectedTimeframe: "4h",
        settings
      })
    ).toBe(true);
  });

  it("matches custom surge, drop, turnover, watch, and quality settings", () => {
    const settings: DashboardViewSettings = normalizeDashboardViewSettings({
      schemaVersion: 1,
      updatedAt: "2026-06-29T00:00:00.000Z",
      views: {
        watch: { kind: "categoryIn", categories: ["WATCH", "CAUTION"] },
        surge: {
          kind: "changePctAtLeast",
          thresholdPctByTimeframe: { "5m": 9, "15m": 4, "1h": 9, "4h": 9, "24h": 9, "74h": 9 },
          excludedCategories: ["NO_TRADE"]
        },
        drop: {
          kind: "changePctAtMostNegative",
          thresholdPctByTimeframe: { "5m": 9, "15m": 3, "1h": 9, "4h": 9, "24h": 9, "74h": 9 },
          excludedCategories: ["NO_TRADE"]
        },
        turnover: {
          kind: "turnoverAtLeast",
          thresholdUsdtByTimeframe: {
            "5m": 1,
            "15m": 500_000,
            "1h": 1,
            "4h": 1,
            "24h": 1,
            "74h": 1
          },
          excludedCategories: ["NO_TRADE"]
        },
        quality: {
          kind: "dataQualityIn",
          allowedDataQualities: ["OK", "PARTIAL"],
          excludedCategories: ["NO_TRADE"]
        }
      }
    });

    expect(
      matchesDashboardView(row({ category: "CAUTION" }), {
        activeCategory: "ALL",
        activeView: "watch",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": 3.9 } }), {
        activeCategory: "ALL",
        activeView: "surge",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": 4 } }), {
        activeCategory: "ALL",
        activeView: "surge",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ changePctByTf: { "15m": -3 } }), {
        activeCategory: "ALL",
        activeView: "drop",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ turnoverUsdtByTf: { "15m": 400_000 } }), {
        activeCategory: "ALL",
        activeView: "turnover",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(false);
    expect(
      matchesDashboardView(row({ dataQuality: "PARTIAL" }), {
        activeCategory: "ALL",
        activeView: "quality",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(true);
    expect(
      matchesDashboardView(row({ category: "NO_TRADE", dataQuality: "PARTIAL" }), {
        activeCategory: "ALL",
        activeView: "quality",
        selectedTimeframe: "15m",
        settings
      })
    ).toBe(false);
  });

  it("normalizes missing and invalid settings file data with defaults", () => {
    const normalized = normalizeDashboardViewSettings({
      schemaVersion: 1,
      updatedAt: "2026-06-29T00:00:00.000Z",
      views: {
        surge: {
          kind: "changePctAtLeast",
          thresholdPctByTimeframe: { "15m": 5, BAD: 100 },
          excludedCategories: ["NO_TRADE", "BAD"]
        },
        quality: {
          kind: "dataQualityIn",
          allowedDataQualities: [],
          excludedCategories: ["NO_TRADE"]
        }
      }
    });

    expect(normalized.views.surge.thresholdPctByTimeframe["15m"]).toBe(5);
    expect(normalized.views.surge.thresholdPctByTimeframe["5m"]).toBe(2);
    expect(normalized.views.surge.excludedCategories).toEqual(["NO_TRADE"]);
    expect(normalized.views.watch.categories).toEqual(["WATCH"]);
    expect(normalized.views.quality.allowedDataQualities).toEqual(["OK"]);
  });
});
