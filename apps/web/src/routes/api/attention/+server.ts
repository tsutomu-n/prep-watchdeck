import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import { AttentionReader } from "$lib/server/attention";

const reader = new AttentionReader();
const headers = { "Cache-Control": "no-store" };
export const GET: RequestHandler = async event => {
  if (!await isLocalhostRequest(event)) return json({ error: "ローカル接続のみ利用できます" }, { status: 403, headers });
  if ([...event.url.searchParams].length) return json({ error: "注目データに検索条件は指定できません" }, { status: 400, headers });
  try { return json(await reader.read(), { headers }); }
  catch { return json({ error: "注目データの取得を待っています" }, { status: 503, headers }); }
};
