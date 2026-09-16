import { describe, expect, test, vi } from "vitest";
import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import type { MarketArtifactBundle } from "./market-artifact-repository";
import { ChartHistoryService } from "./chart-history";

const NOW = Date.parse("2026-09-10T12:02:00.000Z");
const DAY = 86_400_000;
const START = Date.parse("2026-09-10T00:00:00.000Z");

describe("native chart history", () => {
  test("resolves only active grouped linear instruments from a fresh universe before fetching", async () => {
    const fetcher = vi.fn(async () => json([]));
    const bundle = fixture("aster");
    const service = setup(bundle, fetcher);
    for (const parameters of [
      "instrument=aster:BTCUSDT&timeframe=1d",
      "instrument=aster:BTCUSDT&timeframe=5m&url=https://example.com",
      "instrument=aster:BTCUSDT&timeframe=5m&timeframe=1h",
      "instrument=aster:BTCUSDT&timeframe=5m&before=2026-02-30T00:00:00Z",
      "instrument=aster:BTCUSDT&timeframe=5m&before=1789041600000"
    ]) {
      await expect(service.history(new URLSearchParams(parameters))).rejects.toMatchObject({
        status: 400, code: "chart_invalid_request"
      });
    }
    await expect(service.history(query("aster:UNKNOWN"))).rejects.toMatchObject({ status: 404 });
    bundle.universe.items[0].groupId = null;
    await expect(service.history(query())).rejects.toMatchObject({ status: 404 });
    bundle.universe.items[0].groupId = "crypto:BTC:linear-perp";
    bundle.universe.items[0].active = false;
    await expect(service.history(query())).rejects.toMatchObject({ status: 404 });
    bundle.universe.items[0].active = true;
    bundle.universe.generatedAt = new Date(NOW - 120_001).toISOString();
    await expect(service.history(query())).rejects.toMatchObject({ status: 503 });
    expect(fetcher).not.toHaveBeenCalled();
  });

  test("returns UTC daily candles with an explicit open last bar and exclusive ISO pagination", async () => {
    const fetcher = vi.fn(async (_url: URL) => json([
      asterBar(START), asterBar(START - DAY), asterBar(START - DAY)
    ]));
    const service = setup(fixture("aster"), fetcher);
    const latest = await service.history(query("aster:BTCUSDT", "24h"));
    expect(latest.bars.map((bar) => [bar.bucketAt, bar.complete])).toEqual([
      [new Date(START - DAY).toISOString(), true], [new Date(START).toISOString(), false]
    ]);
    expect(latest.bars[0]).toMatchObject({ open: 100, high: 105, low: 95, close: 102,
      volumeBase: 20, volumeNotional: 2_000 });
    expect(latest.hasMore).toBe(true);
    expect(latest.nextBefore).toBe(new Date(START - DAY).toISOString());
    const previous = await service.history(query("aster:BTCUSDT", "24h", new Date(START).toISOString()));
    expect(previous.bars).toHaveLength(1);
    const url = new URL(fetcher.mock.calls[1][0] as URL);
    expect(url.origin).toBe("https://fapi.asterdex.com");
    expect(url.searchParams.get("endTime")).toBe(String(START - 1));
    expect(url.searchParams.get("interval")).toBe("1d");
  });

  test("keeps 500 Bitget daily bars continuous across floored exclusive provider page boundaries", async () => {
    const before = Date.parse("2026-06-13T00:00:00.000Z");
    const fetcher = vi.fn(async (url: URL) => {
      const start = Number(url.searchParams.get("startTime"));
      const end = Number(url.searchParams.get("endTime"));
      expect(end - start).toBeLessThanOrEqual(90 * DAY);
      expect(url.searchParams.get("limit")).toBe("100");
      expect(url.pathname).toBe("/api/v2/mix/market/history-candles");
      expect(url.searchParams.get("productType")).toBe("USDT-FUTURES");
      expect(url.searchParams.get("granularity")).toBe("1Dutc");
      const rows = [];
      // Observed v2 behavior: floor endTime to the interval, then exclude that bar.
      for (let time = Math.floor(start / DAY) * DAY; time < Math.floor(end / DAY) * DAY; time += DAY) {
        rows.push([String(time), "100", "105", "95", "102", "20", "2000"]);
      }
      return json({ code: "00000", data: rows.reverse() });
    });
    const value = await setup(fixture("bitget"), fetcher)
      .history(query("bitget:BTCUSDT", "24h", new Date(before).toISOString()));
    expect(value.bars).toHaveLength(500);
    expect(fetcher).toHaveBeenCalledTimes(6);
    expect(Date.parse(value.bars[0].bucketAt)).toBe(before - 500 * DAY);
    expect(Date.parse(value.bars[499].bucketAt)).toBe(before - DAY);
    expect(value.bars.map((bar) => Date.parse(bar.bucketAt))).toEqual(
      Array.from({ length: 500 }, (_, index) => before - (500 - index) * DAY)
    );
    expect(new URL(fetcher.mock.calls[0][0]).searchParams.get("endTime")).toBe(String(before));
    expect(value.hasMore).toBe(true);
    expect(value.nextBefore).toBe(value.bars[0].bucketAt);
  });

  test("uses Bitget current candles for the latest page, including the open daily bar", async () => {
    const fetcher = vi.fn(async (url: URL) => {
      expect(url.pathname).toBe("/api/v2/mix/market/candles");
      expect(url.searchParams.get("limit")).toBe("500");
      expect(url.searchParams.get("granularity")).toBe("1Dutc");
      expect(url.searchParams.has("startTime")).toBe(false);
      return json({ code: "00000", data: [
        [String(START), "100", "105", "95", "102", "20", "2000"]
      ] });
    });
    const value = await setup(fixture("bitget"), fetcher).history(query("bitget:BTCUSDT", "24h"));
    expect(value.bars[0].complete).toBe(false);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("uses catalog quote and settlement for Bitget and rejects unsupported products", async () => {
    const bundle = fixture("bitget");
    const item = bundle.universe.items[0];
    Object.assign(item, { quoteAsset: "USDC", settleAsset: "USDC", sourceSymbol: "BTCUSDC",
      venueInstrumentId: "bitget:BTCUSDC" });
    const fetcher = vi.fn(async (_url: URL) => json({ code: "00000", data: [] }));
    const service = setup(bundle, fetcher);
    await service.history(query("bitget:BTCUSDC"));
    expect(new URL(fetcher.mock.calls[0][0] as URL).searchParams.get("productType")).toBe("USDC-FUTURES");
    item.settleAsset = "BTC";
    await expect(service.history(query("bitget:BTCUSDC"))).rejects.toMatchObject({ status: 404 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  test("validates Hyperliquid symbol, native interval and exact close boundary", async () => {
    const fetcher = vi.fn(async (_url: URL, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      expect(body).toMatchObject({ type: "candleSnapshot", req: { coin: "BTC", interval: "1d" } });
      expect(body.req.endTime - body.req.startTime).toBeLessThan(500 * DAY);
      return json([{ t: START, T: START + DAY - 1, s: "BTC", i: "1d",
        o: "100", h: "105", l: "95", c: "102", v: "20" }]);
    });
    const value = await setup(fixture("hyperliquid"), fetcher).history(query("hyperliquid:BTC", "24h"));
    expect(value.bars[0]).toMatchObject({ complete: false, volumeNotional: null });
    expect(value.hasMore).toBe(true);
    expect(value.nextBefore).toBe(new Date(START).toISOString());
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", redirect: "error" });
    for (const invalid of [
      { s: "ETH" }, { i: "4h" }, { T: START + DAY }, { v: "Infinity" }, { t: START / 1_000 }
    ]) {
      const bad = vi.fn(async () => json([{ t: START, T: START + DAY - 1, s: "BTC", i: "1d",
        o: "100", h: "105", l: "95", c: "102", v: "20", ...invalid }]));
      await expect(setup(fixture("hyperliquid"), bad).history(query("hyperliquid:BTC", "24h")))
        .rejects.toMatchObject({ status: 502, code: "chart_source_invalid" });
    }
  });

  test("rejects impossible OHLC, nonfinite/negative values, time misalignment and conflicting duplicates", async () => {
    const cases = [
      [START, "100", "99", "95", "102", "20", START + DAY - 1, "2000", 3],
      [START, "NaN", "105", "95", "102", "20", START + DAY - 1, "2000", 3],
      [START, "100", "105", "95", "102", "-1", START + DAY - 1, "2000", 3],
      asterBar(START + 1), asterBar(START + DAY)
    ];
    for (const row of cases) {
      await expect(setup(fixture("aster"), async () => json([row])).history(query("aster:BTCUSDT", "24h")))
        .rejects.toMatchObject({ code: "chart_source_invalid" });
    }
    const conflict = asterBar(START);
    conflict[4] = "103";
    await expect(setup(fixture("aster"), async () => json([asterBar(START), conflict]))
      .history(query("aster:BTCUSDT", "24h"))).rejects.toMatchObject({ code: "chart_source_invalid" });
  });

  test("deduplicates concurrent requests and rechecks freshness before using its cache", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn(() => new Promise<Response>((done) => { resolve = done; }));
    const bundle = fixture("aster");
    const service = setup(bundle, fetcher);
    const one = service.history(query());
    const two = service.history(query());
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    resolve(json([]));
    expect(await one).toEqual(await two);
    await service.history(query());
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect((await service.history(query())).hasMore).toBe(false);
    expect((await service.history(query())).nextBefore).toBeNull();
    bundle.universe.status = "stale";
    await expect(service.history(query())).rejects.toMatchObject({ code: "chart_market_unavailable" });
  });

  test("expires the latest cache and never returns old data as a successful failed refresh", async () => {
    let now = NOW;
    const bundle = fixture("aster");
    const fetcher = vi.fn(async () => json([]));
    const service = new ChartHistoryService({ artifacts: { latest: async () => bundle },
      fetch: fetcher as typeof fetch, now: () => now });
    await service.history(query());
    now += 30_001;
    fetcher.mockImplementation(async () => { throw new Error("private upstream debug"); });
    await expect(service.history(query())).rejects.toMatchObject({
      code: "chart_source_unavailable", message: "chart_source_unavailable"
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  test("bounds the LRU to 32 pages and reports provider failures without retries", async () => {
    const fetcher = vi.fn(async () => json([]));
    const service = setup(fixture("aster"), fetcher);
    for (let index = 1; index <= 33; index += 1) {
      await service.history(query("aster:BTCUSDT", "24h", new Date(START - index * DAY).toISOString()));
    }
    await service.history(query("aster:BTCUSDT", "24h", new Date(START - DAY).toISOString()));
    expect(fetcher).toHaveBeenCalledTimes(34);
    const limited = vi.fn(async () => new Response("rate limited", { status: 429 }));
    await expect(setup(fixture("aster"), limited).history(query())).rejects.toMatchObject({ status: 502 });
    expect(limited).toHaveBeenCalledTimes(1);
  });

  test("bounds concurrent distinct pages without blocking a matching in-flight request", async () => {
    const release: ((response: Response) => void)[] = [];
    const fetcher = vi.fn(() => new Promise<Response>((resolve) => release.push(resolve)));
    const service = setup(fixture("aster"), fetcher);
    const pending = Array.from({ length: 8 }, (_, index) =>
      service.history(query("aster:BTCUSDT", "24h", new Date(START - index * DAY).toISOString())));
    await Promise.resolve();
    await expect(service.history(query())).rejects.toMatchObject({ code: "chart_history_busy" });
    const duplicate = service.history(query("aster:BTCUSDT", "24h", new Date(START).toISOString()));
    expect(fetcher).toHaveBeenCalledTimes(8);
    for (const resolve of release) resolve(json([]));
    await Promise.all([...pending, duplicate]);
    await service.history(query("aster:BTCUSDT", "24h", new Date(START).toISOString()));
    expect(fetcher).toHaveBeenCalledTimes(8);
  });

  test("paces Bitget starts across keys, frees an aborted slot and leaves other venues independent", async () => {
    vi.useFakeTimers();
    const origin = Date.now();
    const pages: AbortController[] = [];
    const timeout = vi.spyOn(AbortSignal, "timeout").mockImplementation((milliseconds) => {
      const controller = new AbortController();
      if (milliseconds === 30_000) pages.push(controller);
      return controller.signal;
    });
    try {
      const bundle = fixture("bitget");
      bundle.universe.items.push(fixture("aster").universe.items[0]);
      const starts: { venue: string; granularity: string | null; at: number }[] = [];
      const fetcher = vi.fn(async (url: URL) => {
        starts.push({ venue: url.hostname, granularity: url.searchParams.get("granularity"),
          at: Date.now() - origin });
        return json(url.hostname === "api.bitget.com" ? { code: "00000", data: [] } : []);
      });
      const service = new ChartHistoryService({ artifacts: { latest: async () => bundle },
        fetch: fetcher as typeof fetch, now: () => NOW, monotonicNow: Date.now });
      const first = service.history(query("bitget:BTCUSDT", "5m"));
      const second = service.history(query("bitget:BTCUSDT", "15m"));
      const third = service.history(query("bitget:BTCUSDT", "1h"));
      const other = service.history(query("aster:BTCUSDT", "5m"));
      const aborted = expect(second).rejects.toMatchObject({ status: 504, code: "chart_source_timeout" });
      await Promise.all([first, other]);
      expect(starts).toEqual(expect.arrayContaining([
        { venue: "api.bitget.com", granularity: "5m", at: 0 },
        { venue: "fapi.asterdex.com", granularity: null, at: 0 }
      ]));
      await vi.advanceTimersByTimeAsync(200);
      pages[1].abort(new DOMException("page timeout", "TimeoutError"));
      await aborted;
      await vi.advanceTimersByTimeAsync(799);
      expect(starts.filter((item) => item.venue === "api.bitget.com")).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(1);
      await third;
      expect(starts.filter((item) => item.venue === "api.bitget.com")).toEqual([
        { venue: "api.bitget.com", granularity: "5m", at: 0 },
        { venue: "api.bitget.com", granularity: "1H", at: 1_000 }
      ]);
    } finally {
      timeout.mockRestore();
      vi.useRealTimers();
    }
  });

  test("shares the in-flight ceiling between chart pages and bounded minute reads", async () => {
    const release: ((response: Response) => void)[] = [];
    const fetcher = vi.fn(() => new Promise<Response>((resolve) => release.push(resolve)));
    const bundle = fixture("aster");
    const service = setup(bundle, fetcher);
    const item = bundle.universe.items[0];
    const pending = Array.from({ length: 8 }, () => service.minuteCandles(item, {
      before: NOW + 1, now: NOW, limit: 3, latest: true
    }));
    await expect(service.history(query())).rejects.toMatchObject({ code: "chart_history_busy" });
    await expect(service.minuteCandles(item, {
      before: NOW + 1, now: NOW, limit: 3, latest: true
    })).rejects.toMatchObject({ code: "chart_history_busy" });
    expect(fetcher).toHaveBeenCalledTimes(8);
    for (const resolve of release) resolve(json([]));
    await Promise.all(pending);
  });
});

function setup(bundle: MarketArtifactBundle, fetcher: (url: URL, init: RequestInit) => Promise<Response>) {
  let clock = 0;
  return new ChartHistoryService({ artifacts: { latest: async () => bundle },
    fetch: fetcher as typeof fetch, now: () => NOW, monotonicNow: () => clock,
    wait: async (milliseconds, signal) => { signal.throwIfAborted(); clock += milliseconds; } });
}

function fixture(venue: UniverseInstrumentArtifact["venue"]): MarketArtifactBundle {
  const symbol = venue === "hyperliquid" ? "BTC" : "BTCUSDT";
  return { universe: {
    generatedAt: new Date(NOW).toISOString(), status: "ready", items: [{
      venue, sourceSymbol: symbol, venueInstrumentId: `${venue}:${symbol}`,
      venueInstrumentVersionId: 1, groupId: "crypto:BTC:linear-perp", active: true,
      marketType: "linear_perpetual", quoteAsset: "USDT", settleAsset: "USDT"
    }]
  } } as MarketArtifactBundle;
}

function query(instrument = "aster:BTCUSDT", timeframe = "5m", before?: string) {
  return new URLSearchParams({ instrument, timeframe, ...(before ? { before } : {}) });
}

function asterBar(start: number): (number | string)[] {
  return [start, "100", "105", "95", "102", "20", start + DAY - 1, "2000", 3];
}

function json(value: unknown) {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}
