import type { RankedRow, RankingResponse } from "$lib/generated/ranking-response";
import type { UserWorkspace } from "$lib/server/user-workspace-repository";
import type { WorkspacePreferences } from "$lib/theme/workspace-preferences";
import type { RankingView } from "./market-view";
import {
  matchesRankingQuery, rankingQuery, RANKING_MAX_AGE_MS,
  type ChartInterval, type RankingOrder, type RankingPeriod
} from "./ranking";

export type RankingViewSnapshot = RankingView & {
  entryId: string;
  period: RankingPeriod;
  order: RankingOrder;
  reference: string;
  minimum: number;
  preset: "standard" | "movement";
  favoritesOnly: boolean;
  lockedIds: string[] | null;
  selectedId: string | null;
  lastSelected: RankedRow | null;
  selectedRemoved: boolean;
  noteTargetId: string;
  selectedViewId: string;
  viewName: string;
  interval: ChartInterval;
  limit: number;
  listScroll: { top: number; left: number };
  pageTop: number;
  detailOpen: boolean;
  workspace: UserWorkspace | null;
};

/** Only defaults that can change the entry view invalidate its restoration. */
export function rankingPreferenceKey(
  preferences: WorkspacePreferences, reference: string
): string {
  return JSON.stringify([
    reference, preferences.initialPeriod, preferences.initialOrder,
    preferences.initialColumns, preferences.referenceViewId, preferences.chartInterval
  ]);
}

export function rankingSnapshotExpired(data: RankingResponse, now: number): boolean {
  const age = now - data.cutoff;
  return data.stale || !Number.isFinite(age) || age < -1000 || age > RANKING_MAX_AGE_MS;
}

function queryKey(parameters: string): string {
  const query = new URLSearchParams(parameters);
  return rankingQuery(query.get("period") as RankingPeriod, query.get("dailyReferenceJst") ?? "",
    query.get("order") as RankingOrder, Number(query.get("minTurnover"))).toString();
}

/** In-memory, bounded data only. No polling or persistent browser storage. */
export class RankingSession {
  private readonly results = new Map<string, RankingResponse>();
  private view: { preferenceKey: string; value: RankingViewSnapshot } | null = null;

  rememberResult(parameters: string, value: RankingResponse): boolean {
    const key = queryKey(parameters);
    if (!matchesRankingQuery(value, new URLSearchParams(key))) return false;
    this.results.delete(key);
    this.results.set(key, value);
    while (this.results.size > 8) this.results.delete(this.results.keys().next().value!);
    return true;
  }

  readResult(parameters: string, now: number) {
    const key = queryKey(parameters);
    const data = this.results.get(key);
    if (!data) return null;
    this.results.delete(key);
    this.results.set(key, data);
    // Keep the original observation times, including when a stale snapshot is revisited.
    return { data, expired: rankingSnapshotExpired(data, now) };
  }

  rememberView(preferenceKey: string, value: RankingViewSnapshot) {
    this.view = { preferenceKey, value };
  }

  restoreView(
    preferenceKey: string, parameters: URLSearchParams, historyEntryId?: string, legacyEntry = false
  ): RankingViewSnapshot | null {
    if (this.view?.preferenceKey !== preferenceKey) return null;
    const saved = this.view.value;
    // Browser Back restores its own view. A new explicit link starts from its requested
    // conditions. Native's return link carries every condition and asks to restore the list.
    const explicit = [...parameters.keys()].some(key => key !== "mode");
    // Direct /rankings entries retain their legacy defaults. A full Native return URL
    // may cross / and /rankings without pretending the browser preferences changed.
    if (legacyEntry && !explicit && historyEntryId !== saved.entryId) return null;
    if (historyEntryId !== saved.entryId && explicit) {
      if (parameters.get("restoreList") !== "1") return null;
      try {
        if (queryKey(parameters.toString()) !== rankingQuery(saved.period, saved.reference,
          saved.order, saved.minimum).toString() || parameters.get("selected") !== saved.selectedId) return null;
      } catch { return null; }
    }
    return saved;
  }
}

let browserSession: RankingSession | undefined;

/** Never create a server singleton holding one browser's view or workspace. */
export function browserRankingSession(): RankingSession | null {
  if (typeof window === "undefined") return null;
  return browserSession ??= new RankingSession();
}
