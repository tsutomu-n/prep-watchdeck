import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import {
  CHART_TIMEFRAMES,
  CHART_TIMEFRAME_SECONDS,
  type ChartCandle,
  type ChartHistory,
  type Timeframe
} from "$lib/market/chart-history";
import {
  createMarketArtifactRepository,
  type MarketArtifactRepository
} from "./market-artifact-repository";

const PAGE_SIZE = 500;
const CACHE_MS = 30_000;
const CACHE_ENTRIES = 32;
const MAX_INFLIGHT = 8;
const REQUEST_TIMEOUT_MS = 10_000;
const PAGE_TIMEOUT_MS = 30_000;
const BITGET_REQUEST_INTERVAL_MS = 1_000;
const DAY_MS = 86_400_000;
const MIN_CANDLE_TIME_MS = Date.UTC(2009, 0, 1);

type ErrorCode =
  | "chart_invalid_request"
  | "chart_instrument_unavailable"
  | "chart_market_unavailable"
  | "chart_source_unavailable"
  | "chart_source_invalid"
  | "chart_source_timeout"
  | "chart_history_busy";

export class ChartHistoryError extends Error {
  constructor(public readonly status: number, public readonly code: ErrorCode) {
    super(code);
  }
}

interface Query {
  instrument: string;
  timeframe: Timeframe;
  before: number | null;
}

export interface MinuteCandleQuery {
  before: number;
  now: number;
  limit: number;
  latest: boolean;
}

interface Options {
  fetch?: typeof globalThis.fetch;
  artifacts?: MarketArtifactRepository;
  now?: () => number;
  monotonicNow?: () => number;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

export class ChartHistoryService {
  private readonly fetcher: typeof globalThis.fetch;
  private readonly artifacts: MarketArtifactRepository;
  private readonly now: () => number;
  private readonly monotonicNow: () => number;
  private readonly wait: (milliseconds: number, signal: AbortSignal) => Promise<void>;
  private bitgetStartQueue: Promise<void> = Promise.resolve();
  private nextBitgetStart = 0;
  private readonly cache = new Map<string, { expiresAt: number; value: ChartHistory }>();
  private readonly inflight = new Map<string, Promise<ChartHistory>>();
  private minuteRequests = 0;

  constructor(options: Options = {}) {
    this.fetcher = options.fetch ?? globalThis.fetch;
    this.artifacts = options.artifacts ?? createMarketArtifactRepository();
    this.now = options.now ?? Date.now;
    this.monotonicNow = options.monotonicNow ?? (() => performance.now());
    this.wait = options.wait ?? waitForRequestSlot;
  }

  async history(parameters: URLSearchParams): Promise<ChartHistory> {
    const now = this.now();
    const query = parseQuery(parameters, now);
    const instrument = await this.resolveInstrument(query.instrument, now);
    const key = JSON.stringify([
      instrument.venueInstrumentId, instrument.venueInstrumentVersionId,
      instrument.quoteAsset, instrument.settleAsset, query.timeframe, query.before
    ]);
    const cached = this.cache.get(key);
    if (cached && cached.expiresAt > now) {
      this.cache.delete(key);
      this.cache.set(key, cached);
      return cached.value;
    }
    this.cache.delete(key);
    const pending = this.inflight.get(key);
    if (pending) return pending;
    if (this.inflight.size + this.minuteRequests >= MAX_INFLIGHT) {
      throw new ChartHistoryError(503, "chart_history_busy");
    }
    const request = this.load(instrument, query, now).then((value) => {
      this.cache.set(key, { expiresAt: this.now() + CACHE_MS, value });
      while (this.cache.size > CACHE_ENTRIES) {
        this.cache.delete(this.cache.keys().next().value!);
      }
      return value;
    }).finally(() => this.inflight.delete(key));
    this.inflight.set(key, request);
    return request;
  }

  async resolveInstrument(id: string, now: number): Promise<UniverseInstrumentArtifact> {
    let universe;
    try {
      universe = (await this.artifacts.latest()).universe;
    } catch {
      throw new ChartHistoryError(503, "chart_market_unavailable");
    }
    const age = now - Date.parse(universe.generatedAt);
    if (!Number.isFinite(age) || Math.abs(age) > 120_000 ||
        universe.status === "stale" || universe.status === "unavailable") {
      throw new ChartHistoryError(503, "chart_market_unavailable");
    }
    const instrument = universe.items.find((item) => item.venueInstrumentId === id);
    if (!instrument?.active || !instrument.groupId || instrument.marketType !== "linear_perpetual" ||
        instrument.venueInstrumentId !== `${instrument.venue}:${instrument.sourceSymbol}`) {
      throw new ChartHistoryError(404, "chart_instrument_unavailable");
    }
    assertSupportedInstrument(instrument);
    return instrument;
  }

  async minuteCandles(instrument: UniverseInstrumentArtifact, query: MinuteCandleQuery) {
    if (!Number.isSafeInteger(query.before) || !Number.isSafeInteger(query.now) ||
        query.before <= MIN_CANDLE_TIME_MS || query.before > query.now + 1 ||
        !Number.isInteger(query.limit) || query.limit < 1 || query.limit > 3 ||
        (!query.latest && query.before % 60_000 !== 0)) {
      throw new ChartHistoryError(400, "chart_invalid_request");
    }
    if (this.inflight.size + this.minuteRequests >= MAX_INFLIGHT) {
      throw new ChartHistoryError(503, "chart_history_busy");
    }
    this.minuteRequests += 1;
    try {
      const signal = AbortSignal.timeout(PAGE_TIMEOUT_MS);
      const bars = instrument.venue === "bitget"
        ? await this.bitget(instrument, "1m", query.before, query.now, signal, query.latest, query.limit)
        : await this.otherVenue(instrument, "1m", query.before, query.now, signal, query.limit);
      return normalizeBars(bars, query.before, query.now, 60_000).slice(-query.limit);
    } finally {
      this.minuteRequests -= 1;
    }
  }

  private async load(instrument: UniverseInstrumentArtifact, query: Query, now: number) {
    const step = CHART_TIMEFRAME_SECONDS[query.timeframe] * 1_000;
    const before = query.before ?? now + 1;
    const pageSignal = AbortSignal.timeout(PAGE_TIMEOUT_MS);
    const bars = instrument.venue === "bitget"
      ? await this.bitget(instrument, query.timeframe, before, now, pageSignal, query.before === null)
      : await this.otherVenue(instrument, query.timeframe, before, now, pageSignal);
    const ordered = normalizeBars(bars, before, now, step).slice(-PAGE_SIZE);
    return {
      venueInstrumentId: instrument.venueInstrumentId,
      timeframe: query.timeframe,
      generatedAt: new Date(now).toISOString(),
      bars: ordered,
      hasMore: ordered.length > 0,
      nextBefore: ordered.length > 0 ? ordered[0].bucketAt : null
    } satisfies ChartHistory;
  }

  private async bitget(
    instrument: UniverseInstrumentArtifact, timeframe: Timeframe | "1m",
    before: number, now: number, signal: AbortSignal, latest: boolean, pageSize = PAGE_SIZE
  ) {
    const step = timeframe === "1m" ? 60_000 : CHART_TIMEFRAME_SECONDS[timeframe] * 1_000;
    // The classic API's explicit 1Dutc keeps daily boundaries at UTC midnight.
    // https://www.bitget.com/docs/uta/enum (candlestick granularity)
    const granularity = { "1m": "1m", "5m": "5m", "15m": "15m", "1h": "1H", "4h": "4H", "24h": "1Dutc" }[timeframe];
    const bars: ChartCandle[] = [];
    let cursor = before;
    // Current candles include the open bar; older daily pages span at most 90 days each.
    for (let page = 0; page < (latest || timeframe === "1m" ? 1 : 6) && bars.length < pageSize; page += 1) {
      // History floors endTime and excludes that interval; subtracting 1ms loses a bar.
      const end = latest ? cursor - 1 : cursor;
      const url = new URL(`https://api.bitget.com/api/v2/mix/market/${latest ? "candles" : "history-candles"}`);
      const parameters = new URLSearchParams({
        productType: `${instrument.quoteAsset}-FUTURES`, symbol: instrument.sourceSymbol,
        granularity, endTime: String(end), limit: String(latest ? pageSize : Math.min(pageSize, 100))
      });
      if (!latest && timeframe !== "1m") {
        parameters.set("startTime", String(Math.max(0, end - Math.min(100 * step, 90 * DAY_MS))));
      }
      url.search = parameters.toString();
      const root = record(await this.request(url, {}, signal));
      if (root.code !== "00000") throw new ChartHistoryError(502, "chart_source_unavailable");
      const rows = array(root.data, (latest ? pageSize : Math.min(pageSize, 100)) + 1);
      const current = normalizeBars(rows.map((row) => {
        const values = array(row, 20);
        if (values.length < 7) invalidSource();
        return candle(values[0], values.slice(1, 5), values[5], values[6], now, step);
      }), cursor, now, step);
      if (!latest && timeframe !== "1m") {
        const earliest = Math.floor(Number(parameters.get("startTime")) / step) * step - step;
        if (current.some((bar) => Date.parse(bar.bucketAt) < earliest)) invalidSource();
      }
      if (!current.length) break;
      bars.push(...current);
      cursor = Date.parse(current[0].bucketAt);
    }
    return bars;
  }

  private async otherVenue(
    instrument: UniverseInstrumentArtifact, timeframe: Timeframe | "1m",
    before: number, now: number, signal: AbortSignal, pageSize = PAGE_SIZE
  ) {
    const step = timeframe === "1m" ? 60_000 : CHART_TIMEFRAME_SECONDS[timeframe] * 1_000;
    const interval = timeframe === "24h" ? "1d" : timeframe;
    const end = before - 1;
    if (instrument.venue === "aster") {
      const url = new URL("https://fapi.asterdex.com/fapi/v1/klines");
      url.search = new URLSearchParams({
        symbol: instrument.sourceSymbol, interval, endTime: String(end), limit: String(pageSize)
      }).toString();
      return array(await this.request(url, {}, signal), pageSize + 1).map((row) => {
        const values = array(row, 20);
        if (values.length < 9) invalidSource();
        assertEnd(values[0], values[6], step);
        return candle(values[0], values.slice(1, 5), values[5], values[7], now, step);
      });
    }
    const start = Math.max(0, Math.floor(end / step) * step - (pageSize - 1) * step);
    const payload = await this.request(new URL("https://api.hyperliquid.xyz/info"), {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ type: "candleSnapshot", req: {
        coin: instrument.sourceSymbol, interval,
        startTime: start,
        endTime: end
      } })
    }, signal);
    return array(payload, pageSize + 1).map((row) => {
      const value = record(row);
      if (value.i !== interval || value.s !== instrument.sourceSymbol) invalidSource();
      if (epoch(value.t) < start) invalidSource();
      assertEnd(value.t, value.T, step);
      return candle(value.t, [value.o, value.h, value.l, value.c], value.v, null, now, step);
    });
  }

  private async request(url: URL, init: RequestInit, pageSignal: AbortSignal): Promise<unknown> {
    let signal = pageSignal;
    try {
      if (url.hostname === "api.bitget.com") await this.paceBitget(pageSignal);
      signal = AbortSignal.any([pageSignal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);
      const response = await this.fetcher(url, { ...init, signal, redirect: "error" });
      if (!response.ok) throw new ChartHistoryError(502, "chart_source_unavailable");
      const body = await response.text();
      if (body.length > 2_000_000) invalidSource();
      try {
        return JSON.parse(body);
      } catch {
        invalidSource();
      }
    } catch (cause) {
      if (cause instanceof ChartHistoryError) throw cause;
      if (signal.aborted) throw new ChartHistoryError(504, "chart_source_timeout");
      throw new ChartHistoryError(502, "chart_source_unavailable");
    }
  }

  private paceBitget(signal: AbortSignal): Promise<void> {
    const slot = this.bitgetStartQueue.then(async () => {
      signal.throwIfAborted();
      const delay = Math.max(0, this.nextBitgetStart - this.monotonicNow());
      if (delay > 0) await this.wait(delay, signal);
      signal.throwIfAborted();
      this.nextBitgetStart = this.monotonicNow() + BITGET_REQUEST_INTERVAL_MS;
    });
    // An aborted page must release the queue for other instruments and timeframes.
    this.bitgetStartQueue = slot.catch(() => undefined);
    return slot;
  }
}

export const chartHistoryService = new ChartHistoryService();

function waitForRequestSlot(milliseconds: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    function abort() {
      clearTimeout(timer);
      reject(signal.reason);
    }
    signal.addEventListener("abort", abort, { once: true });
  });
}

function parseQuery(parameters: URLSearchParams, now: number): Query {
  if ([...parameters.keys()].some((key) => !["instrument", "timeframe", "before"].includes(key)) ||
      ["instrument", "timeframe", "before"].some((key) => parameters.getAll(key).length > 1)) {
    throw new ChartHistoryError(400, "chart_invalid_request");
  }
  const instrument = parameters.get("instrument") ?? "";
  const timeframe = parameters.get("timeframe") ?? "";
  const beforeText = parameters.get("before");
  const before = beforeText === null ? null : Date.parse(beforeText);
  if (!instrument || instrument.length > 160 || instrument !== instrument.trim() ||
      !CHART_TIMEFRAMES.includes(timeframe as Timeframe) ||
      (beforeText !== null && (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(beforeText) ||
        !Number.isSafeInteger(before) || before! <= 0 || before! > now ||
        new Date(before!).toISOString().replace(".000Z", "Z") !== beforeText.replace(".000Z", "Z")))) {
    throw new ChartHistoryError(400, "chart_invalid_request");
  }
  return { instrument, timeframe: timeframe as Timeframe, before };
}

function assertSupportedInstrument(instrument: UniverseInstrumentArtifact) {
  if (!["bitget", "hyperliquid", "aster"].includes(instrument.venue) ||
      !/^[\p{L}\p{N}][\p{L}\p{N}._-]{0,99}$/u.test(instrument.sourceSymbol) ||
      (instrument.venue === "bitget" && (!["USDT", "USDC"].includes(instrument.quoteAsset) ||
        instrument.settleAsset !== instrument.quoteAsset))) {
    throw new ChartHistoryError(404, "chart_instrument_unavailable");
  }
}

function normalizeBars(bars: ChartCandle[], before: number, now: number, step: number) {
  const unique = new Map<number, ChartCandle>();
  for (const bar of bars) {
    const start = Date.parse(bar.bucketAt);
    if (start % step !== 0 || start > now) invalidSource();
    if (start >= before) continue;
    const previous = unique.get(start);
    if (previous && JSON.stringify(previous) !== JSON.stringify(bar)) invalidSource();
    unique.set(start, bar);
  }
  return [...unique.entries()].sort(([a], [b]) => a - b).map(([, bar]) => bar);
}

function candle(
  timestamp: unknown, prices: unknown[], base: unknown, notional: unknown,
  now: number, step: number
): ChartCandle {
  const start = epoch(timestamp);
  const [open, high, low, close] = prices.map((value) => number(value, true));
  if (high < Math.max(open, low, close) || low > Math.min(open, high, close)) invalidSource();
  return {
    bucketAt: new Date(start).toISOString(), open, high, low, close,
    volumeBase: base === null ? null : number(base),
    volumeNotional: notional === null ? null : number(notional),
    complete: start + step <= now
  };
}

function assertEnd(start: unknown, end: unknown, step: number) {
  if (epoch(end) !== epoch(start) + step - 1) invalidSource();
}

function epoch(value: unknown): number {
  if ((typeof value !== "number" && (typeof value !== "string" || !/^\d+$/.test(value))) ||
      !Number.isSafeInteger(Number(value)) || Number(value) < MIN_CANDLE_TIME_MS ||
      Number(value) > 8.64e15) invalidSource();
  return Number(value);
}

function number(value: unknown, positive = false): number {
  if ((typeof value !== "number" && (typeof value !== "string" ||
      !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value))) ||
      !Number.isFinite(Number(value)) || (positive ? Number(value) <= 0 : Number(value) < 0)) invalidSource();
  return Number(value);
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) invalidSource();
  return value as Record<string, unknown>;
}

function array(value: unknown, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) invalidSource();
  return value;
}

function invalidSource(): never {
  throw new ChartHistoryError(502, "chart_source_invalid");
}
