import { error } from "@sveltejs/kit";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import type { PageServerLoad } from "./$types";

export const load: PageServerLoad = async event => {
  event.setHeaders({ "Cache-Control": "no-store" });
  if (!await isLocalhostRequest(event)) error(403, "ローカル接続のみ利用できます");
  return {};
};
