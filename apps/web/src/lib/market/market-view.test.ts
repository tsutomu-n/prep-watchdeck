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
