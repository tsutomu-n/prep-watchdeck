import { describe, expect, it } from "vitest";
import { rankingFixture } from "./ranking-test-fixture";
import { approvedWidgetSymbol, indicatorLabel, matchesRankingQuery, rankChangeLabel, rankingQuery, rankingTimestamp, widgetDocument } from "./ranking";

describe("ranking presentation contracts", () => {
  it("binds period and JST reference to the returned request", () => {
    const query = rankingQuery("daily", "09:30", "turnover", 50);
    const response = rankingFixture(query);
    expect(matchesRankingQuery(response, query)).toBe(true);
    expect(matchesRankingQuery(response, rankingQuery("daily", "09:31", "turnover", 50))).toBe(false);
    for (const value of [NaN, Infinity, -1, 1e19]) expect(() => rankingQuery("15m", "00:00", "gainers", value)).toThrow();
  });

  it("only renders independently qualified Widgets for their bound contracts", () => {
    const row = rankingFixture().rows[0];
    expect(approvedWidgetSymbol(row)).toBe("BYBIT:BTCUSDT.P");
    expect(approvedWidgetSymbol({ ...row, widget: { ...row.widget, referenceKey: "old-reference" } })).toBeNull();
    expect(approvedWidgetSymbol({ ...row, widget: { ...row.widget, symbol: "NASDAQ:AAPL" } })).toBeNull();
    expect(approvedWidgetSymbol({ ...row, mappingStatus: "review" })).toBeNull();
  });

  it("creates an isolated document with locked symbol controls and attribution", () => {
    const doc = widgetDocument("BYBIT:BTCUSDT.P", "60", "dark");
    expect(doc).toContain('"hide_top_toolbar":true');
    expect(doc).toContain('"allow_symbol_change":false');
    expect(doc).toContain('"interval":"60"');
    expect(doc).toContain("TradingView提供のチャート");
    expect(() => widgetDocument('BYBIT:BTCUSDT.P</script>', "15", "dark")).toThrow();
  });

  it("uses JST across a UTC date boundary", () => {
    expect(rankingTimestamp(Date.parse("2026-09-11T15:00:00Z"))).toBe("09/12 00:00");
  });

  it("distinguishes a missing comparison from a new or unchanged rank", () => {
    const row = rankingFixture().rows[0];
    expect(rankChangeLabel(row)).toBe("比較不可（初回・再起動後）");
    for (const [delta, label] of [[5, "+5"], [-5, "−5"], [0, "0"]] as const) {
      expect(rankChangeLabel({ ...row, rankChange: { status: "compared", delta, previousRank: 8, reason: null } })).toBe(label);
    }
    expect(rankChangeLabel({ ...row, rankChange: { status: "new", delta: null, previousRank: null, reason: "filtered" } })).toBe("新規");
    expect(rankChangeLabel(row, true)).toBe("比較不可（古い結果）");
    expect(rankChangeLabel({ ...row, rank: null, state: "filtered" })).toBe("順位外（売買代金の下限未満）");
  });

  it("keeps observed zero distinct from absent indicator values", () => {
    expect(indicatorLabel({ status: "ready", value: 0 }, "倍")).toBe("0倍");
    expect(indicatorLabel({ status: "ready", value: 2 }, "倍")).toBe("2.0倍");
    expect(indicatorLabel({ status: "ready", value: 50 }, "%")).toBe("50.0%");
    expect(indicatorLabel({ status: "no_baseline", value: null }, "倍")).toBe("比較基準なし");
    expect(indicatorLabel({ status: "history_missing", value: null }, "%")).toBe("履歴不足");
    expect(indicatorLabel({ status: "unsupported_period", value: null }, "倍")).toBe("15分・1時間のみ");
    expect(indicatorLabel({ status: "invalid_data", value: null }, "%")).toBe("入力不整合");
  });
});
