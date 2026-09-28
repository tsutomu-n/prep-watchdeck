import Ajv from "ajv";
import schema from "../../../../../schemas/ranking-response.schema.json";
import type { RankingResponse } from "$lib/generated/ranking-response";
import { matchesRankingQuery, rankingQuery, type RankingOrder, type RankingPeriod } from "$lib/market/ranking";

const validate = new Ajv({ allErrors: false, strict: false }).compile<RankingResponse>(schema);
const MAX_BYTES = 8 * 1024 * 1024;

export function normalizeRankingQuery(query: URLSearchParams): URLSearchParams {
  const allowed = new Set(["period", "dailyReferenceJst", "order", "minTurnover"]);
  for (const key of query.keys()) {
    if (!allowed.has(key) || query.getAll(key).length !== 1) throw new RangeError("ランキング条件が不正です");
  }
  return rankingQuery((query.get("period") ?? "15m") as RankingPeriod,
    query.get("dailyReferenceJst") ?? "00:00", (query.get("order") ?? "gainers") as RankingOrder,
    Number(query.get("minTurnover") ?? "0"));
}

export class RankingReader {
  constructor(private readonly fetcher: typeof fetch = fetch, private readonly env = process.env) {}

  async read(query: URLSearchParams): Promise<RankingResponse> {
    const normalized = normalizeRankingQuery(query);
    const rawPort = this.env.PREP_WATCHDECK_RANKING_PORT ?? "8769";
    const port = Number(rawPort);
    if (!/^\d+$/.test(rawPort) || port < 1024 || port > 65535 || [5432, 55432].includes(port)) {
      throw new Error("ランキング接続先の設定が不正です");
    }
    const response = await this.fetcher(`http://127.0.0.1:${port}/rankings?${normalized}`, {
      signal: AbortSignal.timeout(5000), redirect: "error", cache: "no-store"
    });
    if (!response.ok || !response.body) throw new Error("独立ランキングの取得を待っています");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BYTES) throw new Error("ランキング応答の上限を超えました");
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    const payload: unknown = JSON.parse(Buffer.concat(chunks).toString("utf-8"));
    if (!validate(payload) || !matchesRankingQuery(payload, normalized)) throw new Error("ランキングの形式が不正です");
    const ids = new Set(payload.rows.map((row) => row.id));
    if (ids.size !== payload.rows.length || payload.rows.length !== payload.coverage.rows
      || payload.cutoff % 60_000 !== 0 || payload.generatedAt < payload.cutoff
      || payload.cutoff > Date.now() + 1000) throw new Error("ランキングの世代が不正です");
    return payload;
  }
}
