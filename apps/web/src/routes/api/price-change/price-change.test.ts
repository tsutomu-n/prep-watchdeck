import { afterEach, describe, expect, test, vi } from "vitest";
import type { DailyPriceChange } from "$lib/market/price-change";
import { ChartHistoryError } from "$lib/server/chart-history";
import { PriceChangeError, priceChangeService } from "$lib/server/price-change";
import { GET } from "./+server";

afterEach(() => vi.restoreAllMocks());

describe("GET price-change", () => {
  test("returns a typed daily change without browser caching", async () => {
    const value: DailyPriceChange = {
      venueInstrumentId: "aster:BTCUSDT", venueInstrumentVersionId: 1,
      referenceTime: "00:00", baselineAt: "2026-09-10T15:00:00.000Z",
      generatedAt: "2026-09-11T04:13:20.000Z", status: "ready", reason: null,
      baselinePrice: 100, currentPrice: 110, currentCandleAt: "2026-09-11T04:13:00.000Z",
      changePercent: 10
    };
    const change = vi.spyOn(priceChangeService, "change").mockResolvedValue(value);
    const url = new URL("http://localhost/api/price-change?instrument=aster:BTCUSDT&referenceTime=00:00");
    const response = await GET({ url });
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual(value);
    expect(change).toHaveBeenCalledWith(url.searchParams);
  });

  test("keeps safe status, maps shared source errors and hides unexpected details", async () => {
    const change = vi.spyOn(priceChangeService, "change");
    const url = new URL("http://localhost/api/price-change");
    for (const [cause, status, error] of [
      [new PriceChangeError(400, "price_change_invalid_request"), 400, "price_change_invalid_request"],
      [new ChartHistoryError(404, "chart_instrument_unavailable"), 404, "price_change_instrument_unavailable"],
      [new ChartHistoryError(502, "chart_source_unavailable"), 502, "price_change_source_unavailable"],
      [new ChartHistoryError(504, "chart_source_timeout"), 504, "price_change_source_timeout"],
      [new ChartHistoryError(503, "chart_history_busy"), 503, "price_change_busy"],
      [new Error("private path or provider response"), 503, "price_change_market_unavailable"]
    ] as const) {
      change.mockRejectedValue(cause);
      const response = await GET({ url });
      expect(response.status).toBe(status);
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(await response.json()).toEqual({ error });
    }
  });
});
