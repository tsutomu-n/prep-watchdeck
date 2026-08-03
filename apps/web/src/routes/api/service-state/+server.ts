import { error, json } from "@sveltejs/kit";
import { createServiceStateRepository } from "$lib/server/service-state-repository";

export async function GET() {
  try {
    const state = await createServiceStateRepository().latest();
    if (!state) {
      return json({ ok: false, reason: "service state not found" }, { status: 404 });
    }
    return json(state);
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "service state unavailable");
  }
}
