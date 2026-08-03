type DashboardSnapshotSource = {
  summary?: Record<string, unknown>;
} | null | undefined;

type DashboardServiceState = {
  view?: {
    status?: string;
  };
} | null | undefined;

export function shouldAutoRefreshDashboard(
  snapshot: DashboardSnapshotSource,
  serviceState: DashboardServiceState,
  visibilityState: DocumentVisibilityState
) {
  const status = serviceState?.view?.status;
  return (
    snapshot?.summary?.serviceSource === "duckdb-service" &&
    (status === "ok" || status === "backfilling") &&
    visibilityState === "visible"
  );
}
