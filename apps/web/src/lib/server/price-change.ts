import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
import type { ChartCandle } from "$lib/market/chart-history";
import {
  PRICE_CHANGE_MAX_AGE_MS,
  PRICE_CHANGE_REFRESH_MS,
  calculatePriceChange,
  dailyBaselineAt,
  isReferenceTime,
  type DailyPriceChange
} from "$lib/market/price-change";
import { ChartHistoryError, ChartHistoryService, chartHistoryService } from "./chart-history";

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;
const MISSING_CACHE_MS = 10_000;
const BASELINE_CACHE_ENTRIES = 4_096;
const LATEST_CACHE_ENTRIES = 2_048;

type PriceChangeErrorCode =
  | "price_change_invalid_request"
  | "price_change_instrument_unavailable"
  | "price_change_market_unavailable"
  | "price_change_source_unavailable"
  | "price_change_source_invalid"
  | "price_change_source_timeout"
  | "price_change_busy";

export class PriceChangeError extends Error {
  constructor(public readonly status: number, public readonly code: PriceChangeErrorCode) {
    super(code);
  }
}

interface ObservedCandle {
  candle: ChartCandle | null;
  observedAt: number;
}

type CandleCache = Map<string, { expiresAt: number; value: ObservedCandle }>;
type CandleRequests = Map<string, Promise<ObservedCandle>>;

interface Options {
  source?: Pick<ChartHistoryService, "resolveInstrument" | "minuteCandles">;
  now?: () => number;
}

export class DailyPriceChangeService {
  private readonly source: Pick<ChartHistoryService, "resolveInstrument" | "minuteCandles">;
  private readonly now: () => number;
  private readonly baselines: CandleCache = new Map();
  private readonly latest: CandleCache = new Map();
  private readonly baselineRequests: CandleRequests = new Map();
  private readonly latestRequests: CandleRequests = new Map();

  constructor(options: Options = {}) {
    this.source = options.source ?? chartHistoryService;
    this.now = options.now ?? Date.now;
  }

  async change(parameters: URLSearchParams): Promise<DailyPriceChange> {
    const { instrument: id, referenceTime } = parseQuery(parameters);
    const now = this.now();
    const baselineAt = dailyBaselineAt(now, referenceTime);
    // Resolve every request, even when both prices are cached or already in flight.
    const instrument = await this.source.resolveInstrument(id, now);
    const key = instrumentKey(instrument);
    const latestMinute = Math.floor(now / PRICE_CHANGE_REFRESH_MS) * PRICE_CHANGE_REFRESH_MS;
    const latestObservation = await this.cachedCandle(
      this.latest, this.latestRequests, `${key}:${latestMinute}`, LATEST_CACHE_ENTRIES,
      () => latestMinute + PRICE_CHANGE_REFRESH_MS,
      async () => {
        const bars = await this.source.minuteCandles(instrument, {
          before: now + 1, now, limit: 3, latest: true
        });
        return bars.at(-1) ?? null;
      }
    );
    const baselineObservation = await this.cachedCandle(
      this.baselines, this.baselineRequests, `${key}:${baselineAt}`, BASELINE_CACHE_ENTRIES,
      () => baselineAt + DAY_MS,
      async () => {
        const bars = await this.source.minuteCandles(instrument, {
          before: baselineAt, now, limit: 1, latest: false
        });
        return bars.find((bar) => bar.complete &&
          Date.parse(bar.bucketAt) === baselineAt - MINUTE_MS) ?? null;
      }
    );
    const latest = latestObservation.candle;
    const baseline = baselineObservation.candle;
    const latestAt = latest ? Date.parse(latest.bucketAt) : null;
    const evaluatedAt = this.now();
    const reason = !baseline ? "baseline_missing"
      : !latest ? "latest_missing"
      : latestAt! > evaluatedAt || evaluatedAt - latestAt! > PRICE_CHANGE_MAX_AGE_MS ||
        latestAt! < baselineAt - MINUTE_MS ? "latest_stale" : null;
    const changePercent = reason === null
      ? calculatePriceChange(latest!.close, baseline!.close) : null;
    if (reason === null && changePercent === null) {
      throw new PriceChangeError(502, "price_change_source_invalid");
    }
    return {
      venueInstrumentId: instrument.venueInstrumentId,
      venueInstrumentVersionId: instrument.venueInstrumentVersionId,
      referenceTime,
      baselineAt: new Date(baselineAt).toISOString(),
      generatedAt: new Date(latestObservation.observedAt).toISOString(),
      status: reason === null ? "ready" : "unavailable",
      reason,
      baselinePrice: baseline?.close ?? null,
      currentPrice: latest?.close ?? null,
      currentCandleAt: latest?.bucketAt ?? null,
      changePercent
    };
  }

  private async cachedCandle(
    cache: CandleCache,
    requests: CandleRequests,
    key: string,
    maximum: number,
    positiveExpiresAt: () => number,
    load: () => Promise<ChartCandle | null>
  ): Promise<ObservedCandle> {
    const cached = cache.get(key);
    if (cached && cached.expiresAt > this.now()) {
      cache.delete(key);
      cache.set(key, cached);
      return cached.value;
    }
    cache.delete(key);
    const pending = requests.get(key);
    if (pending) return pending;
    const request = load().then((candle) => {
      const value = { candle, observedAt: this.now() };
      cache.set(key, {
        expiresAt: candle ? positiveExpiresAt() : this.now() + MISSING_CACHE_MS,
        value
      });
      while (cache.size > maximum) cache.delete(cache.keys().next().value!);
      return value;
    }).finally(() => requests.delete(key));
    requests.set(key, request);
    return request;
  }
}

export const priceChangeService = new DailyPriceChangeService();

export function priceChangeFailure(cause: unknown): PriceChangeError {
  if (cause instanceof PriceChangeError) return cause;
  if (cause instanceof ChartHistoryError) {
    const codes: Record<ChartHistoryError["code"], PriceChangeErrorCode> = {
      chart_invalid_request: "price_change_invalid_request",
      chart_instrument_unavailable: "price_change_instrument_unavailable",
      chart_market_unavailable: "price_change_market_unavailable",
      chart_source_unavailable: "price_change_source_unavailable",
      chart_source_invalid: "price_change_source_invalid",
      chart_source_timeout: "price_change_source_timeout",
      chart_history_busy: "price_change_busy"
    };
    return new PriceChangeError(cause.status, codes[cause.code]);
  }
  return new PriceChangeError(503, "price_change_market_unavailable");
}

function parseQuery(parameters: URLSearchParams) {
  const keys = ["instrument", "referenceTime"];
  const instrument = parameters.get("instrument");
  const referenceTime = parameters.get("referenceTime");
  if ([...parameters.keys()].some((key) => !keys.includes(key)) ||
      keys.some((key) => parameters.getAll(key).length !== 1) ||
      !instrument || instrument.length > 160 || instrument !== instrument.trim() ||
      !isReferenceTime(referenceTime)) {
    throw new PriceChangeError(400, "price_change_invalid_request");
  }
  return { instrument, referenceTime };
}

function instrumentKey(instrument: UniverseInstrumentArtifact): string {
  return JSON.stringify([
    instrument.venueInstrumentId, instrument.venueInstrumentVersionId,
    instrument.quoteAsset, instrument.settleAsset
  ]);
}
