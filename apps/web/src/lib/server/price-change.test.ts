import { describe, expect, test, vi } from "vitest";
import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import type { ChartCandle } from "$lib/market/chart-history";
import { dailyBaselineAt } from "$lib/market/price-change";
import { ChartHistoryService, type MinuteCandleQuery } from "./chart-history";
import type { MarketArtifactBundle } from "./market-artifact-repository";
import { DailyPriceChangeService } from "./price-change";

const MINUTE = 60_000;
const DAY = 86_400_000;
const NOW = Date.parse("2026-09-11T04:13:20.000Z");
const ANCHOR = Date.parse("2026-09-10T15:00:00.000Z");
type Venue = UniverseInstrumentArtifact["venue"];

describe("daily price change", () => {
  test("requires exactly one instrument and strict JST referenceTime, with no extra parameters", async () => {
    const state = setup();
    for (const input of [
      "", "instrument=aster:BTCUSDT", "referenceTime=00:00",
      "instrument=aster:BTCUSDT&refTime=00:00",
      "instrument=aster:BTCUSDT&referenceTime=0:00",
      "instrument=aster:BTCUSDT&referenceTime=24:00",
      "instrument=aster:BTCUSDT&referenceTime=23:60",
      "instrument=aster:BTCUSDT&referenceTime=00:00&referenceTime=01:00",
      "instrument=aster:BTCUSDT&instrument=aster:BTCUSDT&referenceTime=00:00",
      "instrument=aster:BTCUSDT&referenceTime=00:00&before=2020-01-01",
      "instrument=%20aster:BTCUSDT&referenceTime=00:00"
    ]) {
      await expect(state.service.change(new URLSearchParams(input))).rejects.toMatchObject({
        status: 400, code: "price_change_invalid_request"
      });
    }
    expect(state.source.resolveInstrument).not.toHaveBeenCalled();
    expect(state.source.minuteCandles).not.toHaveBeenCalled();
  });

  test("uses the exact preceding minute close and the latest open trade candle, never markPrice", async () => {
    const state = setup();
    const result = await state.service.change(query());
    expect(result).toEqual({
      venueInstrumentId: "aster:BTCUSDT", venueInstrumentVersionId: 1,
      referenceTime: "00:00", baselineAt: new Date(ANCHOR).toISOString(),
      generatedAt: new Date(NOW).toISOString(), status: "ready", reason: null,
      baselinePrice: 100, currentPrice: 110,
      currentCandleAt: new Date(Math.floor(NOW / MINUTE) * MINUTE).toISOString(),
      changePercent: expect.closeTo(10)
    });
    expect(state.source.minuteCandles.mock.calls.map(([, request]) => request)).toEqual([
      { before: NOW + 1, now: NOW, limit: 3, latest: true },
      { before: ANCHOR, now: NOW, limit: 1, latest: false }
    ]);
    for (const id of ["bitget:1000PEPEUSDT", "hyperliquid:kPEPE"]) {
      const scaled = setup(id);
      scaled.read = (_instrument, request) => [bar(request.latest
        ? Math.floor(scaled.now / MINUTE) * MINUTE : request.before - MINUTE,
      request.latest ? 0.0011 : 0.001, !request.latest)];
      expect((await scaled.service.change(query(id))).changePercent).toBeCloseTo(10);
      expect(scaled.source.minuteCandles.mock.calls[0][0].venueInstrumentId).toBe(id);
    }
  });

  test("does not replace a missing exact baseline with an older or incomplete candle", async () => {
    for (const baseline of [[], [bar(ANCHOR - 2 * MINUTE, 100)],
      [bar(ANCHOR - MINUTE, 100, false)]]) {
      const state = setup();
      state.read = (_instrument, request) => request.latest
        ? [bar(Math.floor(NOW / MINUTE) * MINUTE, 110, false)] : baseline;
      expect(await state.service.change(query())).toMatchObject({
        status: "unavailable", reason: "baseline_missing", baselinePrice: null,
        currentPrice: 110, changePercent: null
      });
    }
    const empty = setup();
    empty.read = () => [];
    expect(await empty.service.change(query())).toMatchObject({
      reason: "baseline_missing", currentPrice: null, currentCandleAt: null
    });
  });

  test("distinguishes missing latest data and fixes the exact 120000ms age boundary at candle start", async () => {
    const missing = setup();
    missing.read = (_instrument, request) => request.latest ? [] : [bar(ANCHOR - MINUTE, 100)];
    expect(await missing.service.change(query())).toMatchObject({
      status: "unavailable", reason: "latest_missing", currentPrice: null,
      currentCandleAt: null, changePercent: null
    });
    const state = setup();
    state.now = Math.floor(NOW / MINUTE) * MINUTE;
    const start = state.now - 2 * MINUTE;
    state.read = (_instrument, request) => [bar(request.latest ? start : ANCHOR - MINUTE,
      request.latest ? 110 : 100)];
    expect((await state.service.change(query())).status).toBe("ready");
    state.now += 1;
    expect(await state.service.change(query())).toMatchObject({
      status: "unavailable", reason: "latest_stale", currentPrice: 110,
      currentCandleAt: new Date(start).toISOString(), changePercent: null
    });
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(2);
  });

  test("keeps price observation time on cache hits, shares latest across reference changes and refreshes at the minute", async () => {
    const state = setup();
    const first = await state.service.change(query());
    state.now += 15_000;
    const cached = await state.service.change(query());
    expect(cached.generatedAt).toBe(first.generatedAt);
    await state.service.change(query("aster:BTCUSDT", "03:17"));
    expect(state.source.minuteCandles.mock.calls.filter(([, request]) => request.latest)).toHaveLength(1);
    expect(state.source.minuteCandles.mock.calls.filter(([, request]) => !request.latest)
      .map(([, request]) => request.before)).toEqual([ANCHOR, dailyBaselineAt(state.now, "03:17")]);
    state.now = Math.ceil(NOW / MINUTE) * MINUTE;
    const refreshed = await state.service.change(query());
    expect(refreshed.generatedAt).toBe(new Date(state.now).toISOString());
    expect(state.source.minuteCandles.mock.calls.filter(([, request]) => request.latest)).toHaveLength(2);
    expect(state.source.minuteCandles.mock.calls.filter(([, request]) => !request.latest)).toHaveLength(2);
  });

  test("checks freshness again after baseline network or queue delays", async () => {
    const state = setup();
    state.now = Math.floor(NOW / MINUTE) * MINUTE;
    const start = state.now - MINUTE;
    state.read = (_instrument, request) => {
      if (!request.latest) state.now += MINUTE + 1;
      return [bar(request.latest ? start : ANCHOR - MINUTE, request.latest ? 110 : 100)];
    };
    expect(await state.service.change(query())).toMatchObject({
      status: "unavailable", reason: "latest_stale", changePercent: null,
      generatedAt: new Date(start + MINUTE).toISOString()
    });
  });

  test("rolls the daily baseline and latest cache together at JST midnight", async () => {
    const state = setup();
    state.now = ANCHOR + DAY - 1;
    const before = await state.service.change(query());
    state.now += 1;
    const after = await state.service.change(query());
    expect(before.baselineAt).toBe(new Date(ANCHOR).toISOString());
    expect(after.baselineAt).toBe(new Date(ANCHOR + DAY).toISOString());
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(4);
    expect(after.generatedAt).toBe(new Date(state.now).toISOString());
  });

  test("never joins a new reference minute to a previous-minute latest request still in flight", async () => {
    const state = setup();
    const midnight = ANCHOR + DAY;
    state.now = midnight - 500;
    let releaseOld!: (bars: ChartCandle[]) => void;
    state.source.minuteCandles.mockImplementationOnce(() => new Promise((resolve) => { releaseOld = resolve; }));
    const previousDay = state.service.change(query());
    await vi.waitFor(() => expect(state.source.minuteCandles).toHaveBeenCalledTimes(1));
    state.now = midnight + 100;
    const currentDay = state.service.change(query());
    await vi.waitFor(() => expect(state.source.minuteCandles.mock.calls
      .filter(([, request]) => request.latest)).toHaveLength(2));
    releaseOld([bar(midnight - MINUTE, 99, false)]);
    const current = await currentDay;
    expect(current).toMatchObject({ baselineAt: new Date(midnight).toISOString(),
      currentPrice: 110, baselinePrice: 100, changePercent: expect.closeTo(10) });
    await previousDay;
    await state.service.change(query());
    expect(state.source.minuteCandles.mock.calls.filter(([, request]) => request.latest)).toHaveLength(2);
  });

  test("briefly caches missing baselines, then retries without discarding the latest cache", async () => {
    const state = setup();
    state.read = (_instrument, request) => request.latest
      ? [bar(Math.floor(state.now / MINUTE) * MINUTE, 110, false)] : [];
    expect((await state.service.change(query())).reason).toBe("baseline_missing");
    state.now += 9_999;
    await state.service.change(query());
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(2);
    state.now += 1;
    state.read = (_instrument, request) => [bar(request.latest
      ? Math.floor(state.now / MINUTE) * MINUTE : request.before - MINUTE,
    request.latest ? 110 : 100, !request.latest)];
    expect((await state.service.change(query())).status).toBe("ready");
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(3);
  });

  test("deduplicates price reads while resolving current identity on every request", async () => {
    const state = setup();
    let release!: (bars: ChartCandle[]) => void;
    state.source.minuteCandles.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
    const one = state.service.change(query());
    const two = state.service.change(query());
    await vi.waitFor(() => expect(state.source.minuteCandles).toHaveBeenCalledTimes(1));
    release([bar(Math.floor(NOW / MINUTE) * MINUTE, 110, false)]);
    expect(await one).toEqual(await two);
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(2);
    await state.service.change(query());
    expect(state.source.resolveInstrument).toHaveBeenCalledTimes(3);
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(2);
  });

  test("invalidates both price caches when the catalog version or product changes", async () => {
    const state = setup("bitget:BTCUSDT");
    await state.service.change(query("bitget:BTCUSDT"));
    state.instrument.venueInstrumentVersionId = 2;
    expect((await state.service.change(query("bitget:BTCUSDT"))).venueInstrumentVersionId).toBe(2);
    state.instrument.quoteAsset = "USDC";
    state.instrument.settleAsset = "USDC";
    await state.service.change(query("bitget:BTCUSDT"));
    expect(state.source.minuteCandles).toHaveBeenCalledTimes(6);
  });

  test("bounds baseline and latest LRU caches after many instruments and reference times", async () => {
    const state = setup();
    for (let index = 0; index < 2_049; index += 1) {
      state.instrument.venueInstrumentVersionId = index + 1;
      await state.service.change(query());
    }
    state.instrument.venueInstrumentVersionId = 1;
    state.source.minuteCandles.mockClear();
    await state.service.change(query());
    expect(state.source.minuteCandles.mock.calls.map(([, request]) => request.latest)).toEqual([true]);
    for (let index = 2_049; index < 4_097; index += 1) {
      state.instrument.venueInstrumentVersionId = index + 1;
      await state.service.change(query());
    }
    // Version 2 was the least recently used entry in both bounded caches.
    state.instrument.venueInstrumentVersionId = 2;
    state.source.minuteCandles.mockClear();
    await state.service.change(query());
    expect(state.source.minuteCandles.mock.calls.map(([, request]) => request.latest)).toEqual([true, false]);
  });
});

describe("daily change native provider integration", () => {
  test.each(["bitget", "aster", "hyperliquid"] as Venue[])(
    "%s uses native market 1m windows and preserves the exact source instrument", async (venue) => {
      const item = instrument(venue === "hyperliquid" ? "hyperliquid:kPEPE" : `${venue}:1000PEPEUSDT`);
      const bundle = fixture(item);
      const calls: { url: URL; init: RequestInit }[] = [];
      const fetcher = vi.fn(async (url: URL, init: RequestInit) => {
        calls.push({ url, init });
        const body = venue === "hyperliquid" ? JSON.parse(String(init.body)) : null;
        const latest = venue === "hyperliquid" ? body.req.endTime === NOW
          : venue === "bitget" ? url.pathname.endsWith("/candles") : url.searchParams.get("limit") === "3";
        const start = latest ? Math.floor(NOW / MINUTE) * MINUTE : ANCHOR - MINUTE;
        const close = latest ? 110 : 100;
        if (venue === "hyperliquid") {
          expect(body.req).toMatchObject({ coin: "kPEPE", interval: "1m" });
          expect(body.req.endTime - body.req.startTime).toBeLessThan(3 * MINUTE);
          return json([{ t: start, T: start + MINUTE - 1, s: "kPEPE", i: "1m",
            o: "100", h: "110", l: "100", c: String(close), v: "5" }]);
        }
        expect(url.searchParams.get("symbol")).toBe("1000PEPEUSDT");
        expect(url.searchParams.get(venue === "bitget" ? "granularity" : "interval")).toBe("1m");
        expect(url.searchParams.get("limit")).toBe(latest ? "3" : "1");
        const row = [String(start), "100", "110", "100", String(close), "5"];
        return venue === "bitget" ? json({ code: "00000", data: [[...row, "500"]] })
          : json([[...row, start + MINUTE - 1, "500", 5]]);
      });
      const source = nativeSource(bundle, fetcher);
      const service = new DailyPriceChangeService({ source, now: () => NOW });
      const result = await service.change(query(item.venueInstrumentId));
      expect(result).toMatchObject({ status: "ready", changePercent: expect.closeTo(10),
        baselinePrice: 100, currentPrice: 110 });
      expect(fetcher).toHaveBeenCalledTimes(2);
      if (venue === "bitget") {
        expect(calls.map(({ url }) => [url.pathname, url.searchParams.get("endTime")])).toEqual([
          ["/api/v2/mix/market/candles", String(NOW)],
          ["/api/v2/mix/market/history-candles", String(ANCHOR)]
        ]);
        expect(calls.every(({ url }) => url.searchParams.get("productType") === "USDT-FUTURES")).toBe(true);
      } else if (venue === "aster") {
        expect(calls.map(({ url }) => url.searchParams.get("endTime"))).toEqual([String(NOW), String(ANCHOR - 1)]);
      }
    }
  );

  test("permits catalog-matched Unicode and rejects stale, ungrouped, inactive or changed identity before cached prices", async () => {
    const item = instrument("aster:哈基米USDT");
    const bundle = fixture(item);
    const fetcher = vi.fn(async (url: URL) => {
      expect(url.searchParams.get("symbol")).toBe("哈基米USDT");
      return json([]);
    });
    const source = nativeSource(bundle, fetcher);
    const service = new DailyPriceChangeService({ source, now: () => NOW });
    await service.change(query(item.venueInstrumentId));
    item.groupId = null;
    await expect(service.change(query(item.venueInstrumentId))).rejects.toMatchObject({ status: 404 });
    item.groupId = "crypto:哈基米:linear-perp";
    item.active = false;
    await expect(service.change(query(item.venueInstrumentId))).rejects.toMatchObject({ status: 404 });
    item.active = true;
    item.sourceSymbol = "BTCUSDT";
    await expect(service.change(query(item.venueInstrumentId))).rejects.toMatchObject({ status: 404 });
    item.sourceSymbol = "哈基米USDT";
    bundle.universe.generatedAt = new Date(NOW - 120_001).toISOString();
    await expect(service.change(query(item.venueInstrumentId))).rejects.toMatchObject({ status: 503 });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  test("does not return a cached latest value as fresh when a refresh fails", async () => {
    let now = NOW;
    const item = instrument("aster:BTCUSDT");
    const bundle = fixture(item);
    const fetcher = vi.fn(async (_url: URL) => json([]));
    const source = nativeSource(bundle, fetcher, () => now);
    const service = new DailyPriceChangeService({ source, now: () => now });
    await service.change(query());
    now += MINUTE;
    bundle.universe.generatedAt = new Date(now).toISOString();
    fetcher.mockImplementation(async () => new Response("sensitive provider message", { status: 429 }));
    await expect(service.change(query())).rejects.toMatchObject({ status: 502, code: "chart_source_unavailable" });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  test("shares the Bitget start queue with chart history and never bursts its two price reads", async () => {
    vi.useFakeTimers();
    try {
      const origin = Date.now();
      const starts: { at: number; path: string; interval: string | null }[] = [];
      const item = instrument("bitget:BTCUSDT");
      const fetcher = vi.fn(async (url: URL) => {
        starts.push({ at: Date.now() - origin, path: url.pathname,
          interval: url.searchParams.get("granularity") });
        return json({ code: "00000", data: [] });
      });
      const source = new ChartHistoryService({ artifacts: { latest: async () => fixture(item) },
        fetch: fetcher as typeof fetch, now: () => NOW, monotonicNow: Date.now });
      const service = new DailyPriceChangeService({ source, now: () => NOW });
      const chart = source.history(new URLSearchParams({ instrument: item.venueInstrumentId, timeframe: "5m" }));
      const price = service.change(query(item.venueInstrumentId));
      await chart;
      expect(starts).toEqual([{ at: 0, path: "/api/v2/mix/market/candles", interval: "5m" }]);
      await vi.advanceTimersByTimeAsync(999);
      expect(starts).toHaveLength(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(starts[1]).toEqual({ at: 1_000, path: "/api/v2/mix/market/candles", interval: "1m" });
      await vi.advanceTimersByTimeAsync(1_000);
      await price;
      expect(starts[2]).toEqual({ at: 2_000, path: "/api/v2/mix/market/history-candles", interval: "1m" });
    } finally {
      vi.useRealTimers();
    }
  });
});

function setup(id = "aster:BTCUSDT") {
  const state = {
    now: NOW,
    instrument: instrument(id),
    read: (_instrument: UniverseInstrumentArtifact, request: MinuteCandleQuery): ChartCandle[] =>
      [bar(request.latest ? Math.floor(state.now / MINUTE) * MINUTE : request.before - MINUTE,
        request.latest ? 110 : 100, !request.latest)]
  };
  const source = {
    resolveInstrument: vi.fn(async (_id: string, _now: number) => state.instrument),
    minuteCandles: vi.fn(async (item: UniverseInstrumentArtifact, request: MinuteCandleQuery) =>
      state.read(item, request))
  };
  return Object.assign(state, { source,
    service: new DailyPriceChangeService({ source, now: () => state.now }) });
}

function nativeSource(
  bundle: MarketArtifactBundle,
  fetcher: (url: URL, init: RequestInit) => Promise<Response>,
  now: () => number = () => NOW
) {
  let clock = 0;
  return new ChartHistoryService({ artifacts: { latest: async () => bundle },
    fetch: fetcher as typeof fetch, now, monotonicNow: () => clock,
    wait: async (delay, signal) => { signal.throwIfAborted(); clock += delay; } });
}

function instrument(id: string): UniverseInstrumentArtifact {
  const [venue, sourceSymbol] = id.split(":");
  return { venue, sourceSymbol, venueInstrumentId: id, venueInstrumentVersionId: 1,
    groupId: "crypto:BTC:linear-perp", active: true, marketType: "linear_perpetual",
    quoteAsset: "USDT", settleAsset: venue === "hyperliquid" ? "USDC" : "USDT",
    markPrice: 5_000 } as UniverseInstrumentArtifact;
}

function fixture(item: UniverseInstrumentArtifact): MarketArtifactBundle {
  return { universe: { generatedAt: new Date(NOW).toISOString(), status: "ready",
    items: [item] } } as MarketArtifactBundle;
}

function bar(start: number, close: number, complete = true): ChartCandle {
  return { bucketAt: new Date(start).toISOString(), open: close, high: close, low: close,
    close, complete, volumeBase: null, volumeNotional: null };
}

function query(instrument = "aster:BTCUSDT", referenceTime = "00:00") {
  return new URLSearchParams({ instrument, referenceTime });
}

function json(value: unknown) {
  return new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
}
