import { expect, test } from "vitest";
import { rankingFixture } from "./ranking-test-fixture";
import { filterSortRankingRows, type RankingView } from "./market-view";

const view: RankingView = {
  search: "", venue: "all", includeUnranked: true, minRatio: null, ratioPeriod: "15m",
  minDayPosition: null, maxDayPosition: null, sort: "return15m", direction: "desc"
};

test("raw values sort every fetched row, with missing last and ID tie breaks", () => {
  const rows = rankingFixture().rows;
  const sorted = filterSortRankingRows(rows, view);
  expect(sorted.map((row) => row.asset)).toEqual(["BTC", "ETH", "NOCHART", "SOL", "MISSING"]);
  expect(filterSortRankingRows(rows, { ...view, direction: "asc" }).at(-1)?.asset).toBe("MISSING");
  expect(filterSortRankingRows(rows, { ...view, venue: "aster" })).toHaveLength(5);
  expect(filterSortRankingRows(rows, { ...view, minRatio: 1.5 }).map((row) => row.asset))
    .toEqual(["BTC"]);
});


test("native activity ordering never substitutes reference ratios for missing Bitget history", () => {
  const rows = rankingFixture().rows;
  const native = new Map([
    ["asset:BTC", { "15m": 0.5, "1h": null }],
    ["asset:ETH", { "15m": 4, "1h": null }]
  ]);
  const sorted = filterSortRankingRows(rows, { ...view, sort: "nativeRatio15m" }, native);
  expect(sorted.slice(0, 2).map(row => row.asset)).toEqual(["ETH", "BTC"]);
  expect(filterSortRankingRows(rows, { ...view, sort: "nativeRatio15m", direction: "asc" }, native)
    .slice(0, 2).map(row => row.asset)).toEqual(["BTC", "ETH"]);
  expect(rows.find(row => row.asset === "BTC")!.turnoverRatios["15m"].value).toBe(2);
});
