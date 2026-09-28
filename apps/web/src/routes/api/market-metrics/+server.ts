import { json } from "@sveltejs/kit";
import { readMarketMetrics } from "$lib/server/market-metrics-repository";

export async function GET() {
  try {
    return json(await readMarketMetrics(), { headers: { "cache-control": "no-store" } });
  } catch {
    return json({ error: "market_metrics_unavailable" }, {
      status: 503, headers: { "cache-control": "no-store" }
    });
  }
}
