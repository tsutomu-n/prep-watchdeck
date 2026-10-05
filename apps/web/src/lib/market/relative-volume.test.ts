import { expect, test } from "vitest";
import { rankingFixture } from "./ranking-test-fixture";
import { rankingQuery } from "./ranking";
import { newlyIncreasedRows, relativeVolumeState, turnoverBarHeights } from "./relative-volume";

const cutoff = Date.parse("2026-10-05T04:15:00Z");

test("both prior days must confirm the increase, independently of price direction", () => {
  const rows = rankingFixture(undefined, cutoff).rows;
  const btc = rows.find(row => row.asset === "BTC")!;
  const sol = rows.find(row => row.asset === "SOL")!;
  const flat = rows.find(row => row.asset === "NOCHART")!;
  expect(relativeVolumeState(btc).kind).toBe("up");
  expect(relativeVolumeState(sol).kind).toBe("down");
  expect(relativeVolumeState(flat).kind).toBe("volume");
  btc.turnoverComparison.previousDayRatio.value = 2.9;
  expect(relativeVolumeState(btc).kind).toBeNull();
});

test("missing, zero baselines, and stale values never become a current surge", () => {
  const row = rankingFixture(undefined, cutoff).rows.find(row => row.asset === "BTC")!;
  expect(relativeVolumeState(row, true).kind).toBeNull();
  expect(relativeVolumeState(row, true).reason).toContain("更新停止");
  row.turnoverComparison.twoDaysAgoRatio = { value: null, status: "no_baseline" };
  expect(relativeVolumeState(row).kind).toBeNull();
  row.turnoverComparison.twoDaysAgo = {
    ...row.turnoverComparison.twoDaysAgo, quoteTurnover: null, status: "history_missing"
  };
  expect(turnoverBarHeights(row.turnoverComparison)).toBeNull();
  expect(relativeVolumeState(row).reason).toContain("履歴不足");
});

test("bars use one scale within the instrument and preserve an observed zero", () => {
  const comparison = rankingFixture(undefined, cutoff).rows[0].turnoverComparison;
  comparison.twoDaysAgo.quoteTurnover = 100;
  comparison.previousDay.quoteTurnover = 200;
  comparison.current.quoteTurnover = 400;
  expect(turnoverBarHeights(comparison)).toEqual([6, 12, 24]);
  comparison.current.quoteTurnover = 0;
  expect(turnoverBarHeights(comparison)).toEqual([12, 24, 0]);
});

test("new markers require a continuous published generation and a valid former comparison", () => {
  const previous = rankingFixture(undefined, cutoff);
  const current = rankingFixture(undefined, cutoff + 60_000);
  current.previousGenerationId = previous.generationId;
  current.previousCutoff = cutoff;
  const btc = previous.rows.find(row => row.asset === "BTC")!;
  btc.turnoverComparison.previousDayRatio.value = 1;
  expect([...newlyIncreasedRows(previous, current, cutoff + 68_000)]).toEqual(["asset:BTC"]);
  expect(newlyIncreasedRows(null, current, cutoff + 68_000).size).toBe(0);
  expect(newlyIncreasedRows(previous, current, cutoff + 300_000).size).toBe(0);
  current.previousGenerationId = "missing-generation";
  expect(newlyIncreasedRows(previous, current, cutoff + 68_000).size).toBe(0);
  current.previousGenerationId = previous.generationId;
  btc.turnoverComparison.previousDayRatio = { value: null, status: "history_missing" };
  expect(newlyIncreasedRows(previous, current, cutoff + 68_000).size).toBe(0);
  const otherPeriod = rankingFixture(rankingQuery("1h", "00:00", "gainers", 0), cutoff + 60_000);
  otherPeriod.previousGenerationId = previous.generationId;
  otherPeriod.previousCutoff = cutoff;
  expect(newlyIncreasedRows(previous, otherPeriod, cutoff + 68_000).size).toBe(0);
});

 test("custom thresholds change emphasis without changing market inputs", () => {
  const row = rankingFixture(undefined, cutoff).rows.find(row => row.asset === "BTC")!;
  row.returnPct = 1.5;
  row.turnoverComparison.previousDayRatio.value = 2.5;
  row.turnoverComparison.twoDaysAgoRatio.value = 2.5;
  const before = JSON.stringify(row);
  expect(relativeVolumeState(row, false, { surgeRatio: 2, directionPct: 1 }).kind).toBe("up");
  expect(relativeVolumeState(row, false, { surgeRatio: 2, directionPct: 2 }).kind).toBe("volume");
  expect(relativeVolumeState(row, true, { surgeRatio: 2, directionPct: 1 }).kind).toBeNull();
  expect(JSON.stringify(row)).toBe(before);
});
