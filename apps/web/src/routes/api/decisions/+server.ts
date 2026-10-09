import { isDecisionEvidence } from "$lib/discovery/contract";
import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { isLocalhostRequest, LocalRequestError, readLocalJson } from "$lib/server/localhost-request";
import { LocalFileDecisionRepository, DecisionError, isDecisionInput } from "$lib/server/decision-repository";

const headers = { "cache-control": "no-store" };
function failure(cause: unknown) {
  return cause instanceof DecisionError || cause instanceof LocalRequestError
    ? json({ error: cause.code }, { status: cause.status, headers })
    : json({ error: "decision_unavailable" }, { status: 500, headers });
}
export const GET: RequestHandler = async event => {
  if (!await isLocalhostRequest(event)) return json({ error: "localhost_required" }, { status: 403, headers });
  try { return json(await new LocalFileDecisionRepository().read(), { headers }); }
  catch (cause) { return failure(cause); }
};
export const POST: RequestHandler = async event => {
  try {
    const payload = await readLocalJson(event, 150_000);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new DecisionError(400, "decision_invalid");
    const value = payload as Record<string, unknown>;
    if (Object.keys(value).length !== 2 || !isDecisionInput(value.decision) || !isDecisionEvidence(value.decision) || !Number.isSafeInteger(value.expectedRevision)) {
      throw new DecisionError(400, "decision_invalid");
    }
    return json(await new LocalFileDecisionRepository().save(value.decision, value.expectedRevision as number), { headers });
  } catch (cause) { return failure(cause); }
};
