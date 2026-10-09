import type { FavoriteTarget } from "$lib/server/user-workspace-repository";

export type DecisionInput = {
  id: string;
  action: "watch" | "skip";
  reason: string;
  target: FavoriteTarget;
  episodeId: string;
  snapshot: Record<string, unknown>;
};
export type ManualDecision = DecisionInput & { recordedAt: string };
export type DecisionHistory = { schemaVersion: 1; revision: number; decisions: ManualDecision[] };

/** A skip applies only to the captured identity and condition episode. */
export function episodeSkipped(history: DecisionHistory | null, episodeId: string | null) {
  if (!episodeId) return false;
  const last = history?.decisions.findLast(entry => entry.episodeId === episodeId);
  return last?.action === "skip";
}
