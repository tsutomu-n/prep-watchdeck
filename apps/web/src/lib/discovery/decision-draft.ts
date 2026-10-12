import type { DiscoveryRow } from "$lib/generated/discovery-response";
import type { DecisionInput } from "$lib/market/decisions";
import type { ComparisonPin } from "$lib/server/user-workspace-repository";
import { isDecisionEvidence } from "./contract";

export const DECISION_DRAFT_KEY = "watchdeck:discovery-decision-draft:v1";
export type DecisionDraft = {
  pin: ComparisonPin;
  row: DiscoveryRow;
  action: "watch" | "skip";
  id: string;
  snapshot: Record<string, unknown>;
  reason: string;
  submitted: boolean;
};

export function decisionDraftInput(draft: DecisionDraft): DecisionInput {
  return { id: draft.id, action: draft.action, reason: draft.reason.trim(), target: draft.pin.target,
    episodeId: draft.row.episodeId!, snapshot: draft.snapshot };
}

/** Restore the original evidence as a unit; never rebuild it from the latest observation. */
export function parseDecisionDraft(value: unknown): DecisionDraft | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const draft = value as DecisionDraft;
  if (typeof draft.id !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(draft.id) ||
      !["watch", "skip"].includes(draft.action) || typeof draft.reason !== "string" ||
      draft.reason.length > 2000 || typeof draft.submitted !== "boolean" ||
      (draft.submitted && !draft.reason.trim()) || !draft.pin ||
      !Number.isSafeInteger(draft.pin.discoveredAt) || !draft.pin.snapshot ||
      typeof draft.pin.snapshot !== "object" || Array.isArray(draft.pin.snapshot) ||
      !draft.row || !draft.row.episodeId || !draft.snapshot ||
      JSON.stringify(draft.row) !== JSON.stringify(draft.snapshot.row)) return null;
  return isDecisionEvidence(decisionDraftInput(draft)) ? draft : null;
}
