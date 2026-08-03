import { json } from "@sveltejs/kit";
import { refreshLiveSnapshotWithResult } from "$lib/server/live-refresh";
import { refreshLiveAvailability } from "$lib/server/runtime-target";
import type { RequestEvent } from "./$types";

export async function POST(event: RequestEvent) {
  const availability = refreshLiveAvailability(event.url.hostname);
  if (!availability.ok) {
    return json(
      {
        ok: false,
        error: availability.error,
        message: availability.message,
        runtime: availability.runtime
      },
      { status: availability.status }
    );
  }

  try {
    const result = await refreshLiveSnapshotWithResult();
    return json({
      ok: true,
      message: result.fallback
        ? result.fallback.message
        : "service snapshot refresh completed",
      snapshot: result.snapshot,
      fallback: result.fallback
    });
  } catch (cause) {
    return json(
      {
        ok: false,
        error: "REFRESH_FAILED",
        message: cause instanceof Error ? cause.message : "live refresh failed"
      },
      { status: 503 }
    );
  }
}
