import { json } from "@sveltejs/kit";
import { readNativeActivity } from "$lib/server/native-activity-repository";

export async function GET() {
  try {
    return json(await readNativeActivity(), { headers: { "cache-control": "no-store" } });
  } catch {
    return json({ error: "native_activity_unavailable" }, {
      status: 503, headers: { "cache-control": "no-store" }
    });
  }
}
