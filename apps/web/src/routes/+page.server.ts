import { createSnapshotRepository } from "$lib/server/snapshot-repository";
import { createPastNoteRepository } from "$lib/server/past-note-repository";
import { createServiceStateRepository } from "$lib/server/service-state-repository";
import { createDashboardViewSettingsRepository } from "$lib/server/dashboard-view-settings-repository";
import { slimSnapshotForDashboard } from "$lib/server/dashboard-snapshot";
import { currentRuntimeInfo } from "$lib/server/runtime-target";

export async function load() {
  try {
    const serviceState = await createServiceStateRepository()
      .latest()
      .catch(() => undefined);
    const snapshot = await createSnapshotRepository().latest();
    return {
      snapshot: slimSnapshotForDashboard(snapshot),
      pastNotes: await createPastNoteRepository().list(),
      dashboardViewSettings: await createDashboardViewSettingsRepository().get(),
      serviceState,
      runtime: currentRuntimeInfo()
    };
  } catch (cause) {
    return {
      error: cause instanceof Error ? cause.message : "snapshot unavailable",
      runtime: currentRuntimeInfo()
    };
  }
}
