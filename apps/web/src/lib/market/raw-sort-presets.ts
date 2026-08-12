import type {
  DashboardRawSortState
} from "$lib/market/dashboard-filters";

export const rawSortQuickTimeframes = ["15m", "1h", "24h"] as const;
export const rawSortQuickLenses = [
  { id: "up", label: "上昇" },
  { id: "down", label: "下落" },
  { id: "turnover", label: "売買代金" }
] as const;

export type RawSortQuickLens = (typeof rawSortQuickLenses)[number]["id"];

export const fifteenMinuteVolumeRatioState: DashboardRawSortState = {
  sortKey: "volumeRatio",
  direction: "desc"
};

export function rawSortStateForLens(lens: RawSortQuickLens): DashboardRawSortState {
  if (lens === "down") {
    return { sortKey: "changePct", direction: "asc" };
  }
  if (lens === "turnover") {
    return { sortKey: "turnoverUsdt", direction: "desc" };
  }
  return { sortKey: "changePct", direction: "desc" };
}

export function rawSortStateForTimeframe(current: DashboardRawSortState): DashboardRawSortState {
  return isFifteenMinuteVolumeRatioState(current) ? rawSortStateForLens("up") : current;
}

export function rawSortLensForState(state: DashboardRawSortState): RawSortQuickLens | null {
  if (state.sortKey === "changePct" && state.direction === "desc") return "up";
  if (state.sortKey === "changePct" && state.direction === "asc") return "down";
  if (state.sortKey === "turnoverUsdt" && state.direction === "desc") return "turnover";
  return null;
}

export function isFifteenMinuteVolumeRatioState(state: DashboardRawSortState) {
  return (
    state.sortKey === fifteenMinuteVolumeRatioState.sortKey &&
    state.direction === fifteenMinuteVolumeRatioState.direction
  );
}

export function isQuickLensActive(state: DashboardRawSortState, lens: RawSortQuickLens) {
  return rawSortLensForState(state) === lens;
}
