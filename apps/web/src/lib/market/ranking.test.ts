import { describe, expect, it } from "vitest";
import { rankingFixture } from "./ranking-test-fixture";
import { approvedWidgetSymbol, matchesRankingQuery, rankingQuery, rankingTimestamp, widgetDocument } from "./ranking";

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
});
