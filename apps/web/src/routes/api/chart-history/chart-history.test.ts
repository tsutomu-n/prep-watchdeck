import { afterEach, describe, expect, test, vi } from "vitest";
import { ChartHistoryError, chartHistoryService } from "$lib/server/chart-history";
import { GET } from "./+server";

afterEach(() => vi.restoreAllMocks());

describe("GET chart-history", () => {
  test("serves typed history without browser caching", async () => {
    const value = { venueInstrumentId: "aster:BTCUSDT", timeframe: "24h" as const,
      generatedAt: "2026-09-10T12:00:00.000Z", bars: [], hasMore: false, nextBefore: null };
    const history = vi.spyOn(chartHistoryService, "history").mockResolvedValue(value);
    const url = new URL("http://localhost/api/chart-history?instrument=aster:BTCUSDT&timeframe=24h");
    const response = await GET({ url });
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual(value);
    expect(history).toHaveBeenCalledWith(url.searchParams);
  });

  test("preserves safe error status and hides unexpected error details", async () => {
    const history = vi.spyOn(chartHistoryService, "history");
    const url = new URL("http://localhost/api/chart-history");
    history.mockRejectedValue(new ChartHistoryError(400, "chart_invalid_request"));
    const invalid = await GET({ url });
    expect(invalid.status).toBe(400);
    expect(await invalid.json()).toEqual({ error: "chart_invalid_request" });
    history.mockRejectedValue(new Error("private path or upstream response"));
    const unavailable = await GET({ url });
    expect(unavailable.status).toBe(503);
    expect(unavailable.headers.get("cache-control")).toBe("no-store");
    expect(await unavailable.json()).toEqual({ error: "chart_market_unavailable" });
  });
});
