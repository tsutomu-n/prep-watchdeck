import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import { DiscoveryError, DiscoveryReader } from "$lib/server/discovery";

const reader = new DiscoveryReader();
const headers = { "cache-control": "no-store" };
export const GET: RequestHandler = async event => {
  if (!await isLocalhostRequest(event)) return json({ error: "localhost_required" }, { status: 403, headers });
  try { return json(await reader.read(event.url.searchParams), { headers }); }
  catch (cause) { return json({ error: cause instanceof DiscoveryError ? cause.code : "discovery_unavailable" },
    { status: cause instanceof DiscoveryError ? cause.status : 503, headers }); }
};
