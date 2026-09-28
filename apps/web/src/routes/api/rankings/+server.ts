import { json } from "@sveltejs/kit";
import type { RequestHandler } from "./$types";
import { isLocalhostRequest } from "$lib/server/localhost-request";
import { RankingReader } from "$lib/server/ranking";

const reader = new RankingReader();

export const GET: RequestHandler = async (event) => {
  if (!isLocalhostRequest(event)) return json({ error: "ローカル接続のみ利用できます" }, { status: 403 });
  try {
    return json(await reader.read(event.url.searchParams), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof RangeError ? 400 : 503;
    return json({ error: status === 400 ? "ランキング条件が不正です" : "独立ランキングの取得を待っています" },
      { status, headers: { "Cache-Control": "no-store" } });
  }
};
