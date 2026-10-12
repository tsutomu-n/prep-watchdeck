import { expect, test } from "vitest";
import { defaultPreferences } from "$lib/theme/workspace-preferences";
import { rankingFixture } from "./ranking-test-fixture";
import { rankingQuery } from "./ranking";
import {
  browserRankingSession, RankingSession, rankingPreferenceKey, type RankingViewSnapshot
} from "./ranking-session";

const cutoff = Date.parse("2026-10-09T03:00:00Z");
const parameters = rankingQuery("24h", "00:00", "turnover", 0);
const key = rankingPreferenceKey(defaultPreferences, "00:00");

function view(): RankingViewSnapshot {
  return {
    entryId: "entry-1",
    period: "24h", order: "turnover", reference: "00:00", minimum: 0,
    search: "BTC", venue: "all", includeUnranked: true, favoritesOnly: false,
    ratioPeriod: "15m", minRatio: null, minDayPosition: null, maxDayPosition: null,
    sort: "asset", direction: "desc", preset: "movement", lockedIds: ["asset:BTC"],
    selectedId: "asset:BTC", lastSelected: null, selectedRemoved: false, noteTargetId: "",
    selectedViewId: "", viewName: "", interval: "15", limit: 100,
    listScroll: { top: 180, left: 70 }, pageTop: 250, detailOpen: false, workspace: null
  };
}

test("restores an exact query without refreshing its source cutoff or masking expiration", () => {
  const session = new RankingSession();
  const payload = rankingFixture(parameters, cutoff);
  expect(session.rememberResult(parameters.toString(), payload)).toBe(true);
  expect(session.readResult(parameters.toString(), cutoff + 30_000)).toEqual({ data: payload, expired: false });
  const expired = session.readResult(parameters.toString(), cutoff + 150_001)!;
  expect(expired.expired).toBe(true);
  expect(expired.data.cutoff).toBe(cutoff);
  expect(expired.data.generatedAt).toBe(cutoff + 8000);
  expect(session.readResult(rankingQuery("1h", "00:00", "turnover", 0).toString(), cutoff)).toBeNull();
  expect(session.rememberResult(parameters.toString(), rankingFixture())).toBe(false);
  expect(session.readResult(parameters.toString(), cutoff + 30_000)?.data).toBe(payload);
});

test("keeps at most eight recent query results and does not instantiate a server session", () => {
  const session = new RankingSession();
  for (let minimum = 0; minimum < 9; minimum += 1) {
    const query = rankingQuery("24h", "00:00", "turnover", minimum);
    session.rememberResult(query.toString(), rankingFixture(query, cutoff));
  }
  expect(session.readResult(parameters.toString(), cutoff)).toBeNull();
  expect(session.readResult(rankingQuery("24h", "00:00", "turnover", 8).toString(), cutoff)).not.toBeNull();
  expect(browserRankingSession()).toBeNull();
});

test("restores view and scroll for menu/native returns, while explicit queries and changed defaults win", () => {
  const session = new RankingSession();
  const saved = view();
  session.rememberView(key, saved);
  expect(session.restoreView(key, new URLSearchParams("mode=reference"))).toEqual(saved);
  const nativeReturn = new URLSearchParams(parameters);
  nativeReturn.set("restoreList", "1"); nativeReturn.set("selected", "asset:BTC");
  expect(session.restoreView(key, nativeReturn)).toEqual(saved);
  expect(session.restoreView(key, nativeReturn, undefined, true)).toEqual(saved);
  expect(session.restoreView(key, new URLSearchParams(), undefined, true)).toBeNull();
  expect(session.restoreView(key, new URLSearchParams(), "entry-1", true)).toEqual(saved);
  nativeReturn.set("period", "1h");
  expect(session.restoreView(key, nativeReturn)).toBeNull();
  expect(session.restoreView(key, new URLSearchParams("selected=asset:BTC"), "entry-1")).toEqual(saved);
  for (const query of ["period=1h", "q=ETH", "selected=asset:ETH"]) {
    expect(session.restoreView(key, new URLSearchParams(query))).toBeNull();
  }
  for (const next of [
    rankingPreferenceKey({ ...defaultPreferences, initialPeriod: "1h" }, "00:00"),
    rankingPreferenceKey({ ...defaultPreferences, referenceViewId: "new-view" }, "00:00"),
    rankingPreferenceKey(defaultPreferences, "09:00")
  ]) expect(session.restoreView(next, new URLSearchParams())).toBeNull();
  // Formatting preferences apply immediately without discarding the user's list position.
  expect(rankingPreferenceKey({ ...defaultPreferences, percentDecimals: 4 }, "00:00")).toBe(key);
});
