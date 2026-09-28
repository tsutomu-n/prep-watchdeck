import {
  DEFAULT_REFERENCE_TIME,
  PRICE_CHANGE_MAX_AGE_MS,
  PRICE_CHANGE_REFRESH_MS,
  calculatePriceChange,
  dailyBaselineAt,
  isReferenceTime,
  priceChangeUnavailableLabel,
  type DailyPriceChange
} from "./price-change";

export interface PriceChangeTarget {
  venueInstrumentId: string;
  venueInstrumentVersionId: number;
}

export interface PriceChangeState {
  status: "idle" | "queued" | "loading" | "ready" | "unavailable" | "error" | "stale";
  data: DailyPriceChange | null;
  message: string | null;
}

interface PriceChangeClientOptions {
  onUpdate: (id: string, state: PriceChangeState) => void;
  fetch?: typeof fetch;
  now?: () => number;
  referenceTime?: string;
}

interface TargetEntry {
  target: PriceChangeTarget;
  state: PriceChangeState;
  nextAttemptAt: number;
  request: ActiveRequest | null;
}

interface ActiveRequest {
  entry: TargetEntry;
  generation: number;
  referenceTime: string;
  baselineAt: number;
  controller: AbortController;
  cancelled: boolean;
}

interface CachedResult {
  version: number;
  state: PriceChangeState;
  nextAttemptAt: number;
}

const MAX_CONCURRENT_REQUESTS = 2;
const MAX_CACHED_RESULTS = 256;
const emptyState = (status: PriceChangeState["status"] = "idle"): PriceChangeState => ({
  status,
  data: null,
  message: null
});

function positivePrice(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function timestamp(value: unknown): number {
  return typeof value === "string" ? Date.parse(value) : NaN;
}

function responseState(value: unknown, request: ActiveRequest, now: number): PriceChangeState {
  const invalid = () => new Error("値動きデータを確認できません");
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  const data = value as DailyPriceChange;
  const generatedAt = timestamp(data.generatedAt);
  const currentCandleAt = timestamp(data.currentCandleAt);
  if (
    data.venueInstrumentId !== request.entry.target.venueInstrumentId ||
    data.venueInstrumentVersionId !== request.entry.target.venueInstrumentVersionId ||
    data.referenceTime !== request.referenceTime ||
    timestamp(data.baselineAt) !== request.baselineAt ||
    !Number.isFinite(generatedAt) || generatedAt > now || generatedAt < request.baselineAt ||
    (data.baselinePrice !== null && !positivePrice(data.baselinePrice)) ||
    (data.currentPrice !== null && !positivePrice(data.currentPrice)) ||
    (data.currentPrice === null
      ? data.currentCandleAt !== null
      : !Number.isFinite(currentCandleAt) || currentCandleAt > generatedAt)
  ) throw invalid();

  if (data.status === "ready") {
    if (
      data.reason !== null || !positivePrice(data.baselinePrice) ||
      !positivePrice(data.currentPrice) || currentCandleAt < request.baselineAt - 60_000 ||
      typeof data.changePercent !== "number" || !Number.isFinite(data.changePercent)
    ) throw invalid();
    const expected = calculatePriceChange(data.currentPrice, data.baselinePrice);
    if (expected === null || Math.abs(data.changePercent - expected) > 1e-8 * Math.max(1, Math.abs(expected))) {
      throw invalid();
    }
  } else if (data.status === "unavailable") {
    if (data.changePercent !== null) throw invalid();
    switch (data.reason) {
      case "baseline_missing":
        if (data.baselinePrice !== null) throw invalid();
        break;
      case "latest_missing":
        if (data.currentPrice !== null || data.currentCandleAt !== null) throw invalid();
        break;
      case "latest_stale":
        if (!positivePrice(data.currentPrice) || !Number.isFinite(currentCandleAt)) throw invalid();
        break;
      default:
        throw invalid();
    }
  } else {
    throw invalid();
  }

  if (
    now - generatedAt > PRICE_CHANGE_MAX_AGE_MS ||
    (data.status === "ready" && now - currentCandleAt > PRICE_CHANGE_MAX_AGE_MS)
  ) {
    return { status: "stale", data: null, message: "値動きデータが古くなりました" };
  }
  return {
    status: data.status,
    data,
    message: data.reason === null ? null : priceChangeUnavailableLabel(data.reason)
  };
}

/** The page owns refresh/visibility timers; this client only fetches its current targets. */
export class PriceChangeClient {
  private readonly onUpdate: PriceChangeClientOptions["onUpdate"];
  private readonly fetcher: typeof fetch;
  private readonly now: () => number;
  private referenceTime: string;
  private baselineAt: number;
  private generation = 0;
  private entries = new Map<string, TargetEntry>();
  private readonly cache = new Map<string, CachedResult>();
  private readonly active = new Set<ActiveRequest>();
  private paused = false;
  private disposed = false;

  constructor(options: PriceChangeClientOptions) {
    this.onUpdate = options.onUpdate;
    this.fetcher = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.now = options.now ?? Date.now;
    this.referenceTime = options.referenceTime ?? DEFAULT_REFERENCE_TIME;
    this.baselineAt = dailyBaselineAt(this.now(), this.referenceTime);
  }

  setTargets(items: readonly PriceChangeTarget[]): void {
    if (this.disposed) return;
    const now = this.now();
    this.synchronizeContext(now);
    const targets = new Map<string, PriceChangeTarget>();
    for (const item of items) {
      if (!targets.has(item.venueInstrumentId)) targets.set(item.venueInstrumentId, { ...item });
    }
    for (const [id, entry] of this.entries) {
      if (targets.get(id)?.venueInstrumentVersionId === entry.target.venueInstrumentVersionId) continue;
      this.cancel(entry);
      this.publish(entry, emptyState());
    }
    const entries = new Map<string, TargetEntry>();
    for (const [id, target] of targets) {
      const existing = this.entries.get(id);
      if (existing?.target.venueInstrumentVersionId === target.venueInstrumentVersionId) {
        entries.set(id, existing);
        continue;
      }
      const cached = this.cache.get(id);
      const reusable = cached?.version === target.venueInstrumentVersionId && cached.nextAttemptAt > now;
      const entry: TargetEntry = {
        target,
        state: reusable ? cached.state : emptyState(),
        nextAttemptAt: reusable ? cached.nextAttemptAt : 0,
        request: null
      };
      entries.set(id, entry);
      if (reusable) {
        this.cache.delete(id);
        this.cache.set(id, cached);
      } else {
        this.cache.delete(id);
      }
      this.publish(entry, entry.state);
    }
    this.entries = entries;
    this.reconcile(now);
  }

  setReferenceTime(referenceTime: string): void {
    if (this.disposed) return;
    if (!isReferenceTime(referenceTime)) throw new RangeError("Invalid daily reference time");
    if (referenceTime !== this.referenceTime) {
      this.referenceTime = referenceTime;
      this.resetContext(dailyBaselineAt(this.now(), referenceTime));
    }
    this.refresh();
  }

  refresh(): void {
    if (!this.disposed) this.reconcile(this.now());
  }

  setPaused(paused: boolean): void {
    if (this.disposed) return;
    this.paused = paused;
    this.synchronizeContext(this.now());
    if (paused) {
      for (const entry of this.entries.values()) {
        if (!entry.request && entry.state.status !== "queued") continue;
        this.cancel(entry);
        entry.nextAttemptAt = 0;
        this.publish(entry, emptyState());
      }
    }
    this.refresh();
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    for (const request of this.active) {
      request.cancelled = true;
      request.controller.abort();
    }
    this.entries.clear();
    this.cache.clear();
  }

  private publish(entry: TargetEntry, state: PriceChangeState): void {
    entry.state = state;
    this.onUpdate(entry.target.venueInstrumentId, state);
  }

  private cancel(entry: TargetEntry): void {
    if (!entry.request) return;
    entry.request.cancelled = true;
    entry.request.controller.abort();
    entry.request = null;
  }

  private synchronizeContext(now: number): void {
    const baselineAt = dailyBaselineAt(now, this.referenceTime);
    if (baselineAt !== this.baselineAt) this.resetContext(baselineAt);
  }

  private resetContext(baselineAt: number): void {
    this.baselineAt = baselineAt;
    this.generation += 1;
    this.cache.clear();
    for (const entry of this.entries.values()) {
      this.cancel(entry);
      entry.nextAttemptAt = 0;
      this.publish(entry, emptyState());
    }
  }

  private reconcile(now: number): void {
    this.synchronizeContext(now);
    for (const entry of this.entries.values()) {
      const data = entry.state.data;
      if (data && (
        now - Date.parse(data.generatedAt) > PRICE_CHANGE_MAX_AGE_MS ||
        (entry.state.status === "ready" && now - timestamp(data.currentCandleAt) > PRICE_CHANGE_MAX_AGE_MS)
      )) {
        entry.nextAttemptAt = Math.min(entry.nextAttemptAt, now);
        this.cache.delete(entry.target.venueInstrumentId);
        this.publish(entry, { status: "stale", data: null, message: "値動きデータが古くなりました" });
      }
      if (this.paused || entry.request || entry.nextAttemptAt > now || entry.state.status === "queued") continue;
      this.publish(entry, emptyState("queued"));
    }
    if (this.paused) return;
    for (const entry of this.entries.values()) {
      if (this.active.size >= MAX_CONCURRENT_REQUESTS) break;
      if (entry.state.status !== "queued" || entry.request) continue;
      const request: ActiveRequest = {
        entry,
        generation: this.generation,
        referenceTime: this.referenceTime,
        baselineAt: this.baselineAt,
        controller: new AbortController(),
        cancelled: false
      };
      entry.request = request;
      this.active.add(request);
      this.publish(entry, emptyState("loading"));
      void this.load(request);
    }
  }

  private isCurrent(request: ActiveRequest): boolean {
    return !this.disposed && !this.paused && !request.cancelled &&
      request.generation === this.generation &&
      this.entries.get(request.entry.target.venueInstrumentId) === request.entry &&
      request.entry.request === request;
  }

  private settle(request: ActiveRequest, state: PriceChangeState, now: number): void {
    const entry = request.entry;
    entry.nextAttemptAt = now + PRICE_CHANGE_REFRESH_MS;
    const id = entry.target.venueInstrumentId;
    this.cache.delete(id);
    this.cache.set(id, {
      version: entry.target.venueInstrumentVersionId,
      state,
      nextAttemptAt: entry.nextAttemptAt
    });
    while (this.cache.size > MAX_CACHED_RESULTS) this.cache.delete(this.cache.keys().next().value!);
    this.publish(entry, state);
  }

  private async load(request: ActiveRequest): Promise<void> {
    try {
      const query = new URLSearchParams({
        instrument: request.entry.target.venueInstrumentId,
        referenceTime: request.referenceTime
      });
      const response = await this.fetcher(`/api/price-change?${query}`, {
        signal: request.controller.signal,
        cache: "no-store"
      });
      if (!response.ok) throw new Error(`値動きの取得に失敗しました (${response.status})`);
      const value: unknown = await response.json();
      const now = this.now();
      this.synchronizeContext(now);
      if (this.isCurrent(request)) this.settle(request, responseState(value, request, now), now);
    } catch (error) {
      const now = this.now();
      if (!this.disposed) this.synchronizeContext(now);
      if (this.isCurrent(request)) {
        this.settle(request, {
          status: "error",
          data: null,
          message: error instanceof Error && error.message.startsWith("値動き")
            ? error.message : "値動きの取得に失敗しました"
        }, now);
      }
    } finally {
      // An aborted fetch may ignore its signal. It occupies a slot until it actually settles.
      this.active.delete(request);
      if (request.entry.request === request) request.entry.request = null;
      if (!this.disposed) this.reconcile(this.now());
    }
  }
}
