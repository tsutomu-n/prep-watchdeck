import { json } from "@sveltejs/kit";
import { ChartHistoryError, chartHistoryService } from "$lib/server/chart-history";

export async function GET({ url }: { url: URL }) {
  const headers = { "cache-control": "no-store" };
  try {
    return json(await chartHistoryService.history(url.searchParams), { headers });
  } catch (cause) {
    const failure = cause instanceof ChartHistoryError
      ? cause
      : new ChartHistoryError(503, "chart_market_unavailable");
    return json({ error: failure.code }, { status: failure.status, headers });
  }
}
