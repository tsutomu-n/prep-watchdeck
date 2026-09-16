import { json } from "@sveltejs/kit";
import { priceChangeFailure, priceChangeService } from "$lib/server/price-change";

export async function GET({ url }: { url: URL }) {
  const headers = { "cache-control": "no-store" };
  try {
    return json(await priceChangeService.change(url.searchParams), { headers });
  } catch (cause) {
    const failure = priceChangeFailure(cause);
    return json({ error: failure.code }, { status: failure.status, headers });
  }
}
