import { SvelteMap } from "svelte/reactivity";

const tickerStaleAfterMs = 5_000;
const tickerPollIntervalMs = 1_000;
const tickerRetryMaximumMs = 10_000;

export type TickerRuntimeUpdate = [symbol: string, lastPrice: number, ts: number];

export type TickerRuntimeBatch = {
  schemaVersion: 1;
  sequence: number;
  asOf: number;
  full: boolean;
  updates: TickerRuntimeUpdate[];
};

export type TickerValue = {
  lastPrice: number;
  ts: number;
  stale: boolean;
};

export type TickerPriceView = {
  value: number | null;
  source: "hot" | "snapshot" | "analysis" | "missing";
  stale: boolean;
};

export type TickerApplyResult = "applied" | "gap" | "ignored";

export class TickerOverlay {
  readonly tickers = new SvelteMap<string, TickerValue>();
  private readonly hotPriceViews = new WeakMap<TickerValue, TickerPriceView>();
  private readonly metadata = new SvelteMap<"sequence" | "asOf", number>([
    ["sequence", 0],
    ["asOf", 0]
  ]);

  get sequence() {
    return this.metadata.get("sequence") ?? 0;
  }

  get asOf() {
    return this.metadata.get("asOf") ?? 0;
  }

  applyBatch(batch: TickerRuntimeBatch): TickerApplyResult {
    if (batch.full) {
      if (batch.sequence < this.sequence) return "ignored";
      this.tickers.clear();
      this.applyUpdates(batch.updates);
      this.setMetadata(batch);
      return "applied";
    }

    if (
      this.sequence === 0 ||
      batch.sequence <= this.sequence ||
      batch.sequence !== this.sequence + 1
    ) {
      return "gap";
    }

    this.applyUpdates(batch.updates);
    this.setMetadata(batch);
    return "applied";
  }

  refreshStaleness(nowMs = Date.now()): string[] {
    const changed: string[] = [];
    for (const [symbol, ticker] of this.tickers) {
      const stale = nowMs - ticker.ts > tickerStaleAfterMs;
      if (ticker.stale === stale) continue;
      this.tickers.set(symbol, { ...ticker, stale });
      changed.push(symbol);
    }
    return changed;
  }

  nextStaleAtMs(nowMs = Date.now()): number | null {
    let next: number | null = null;
    for (const ticker of this.tickers.values()) {
      if (ticker.stale) continue;
      const boundary = ticker.ts + tickerStaleAfterMs + 1;
      if (boundary <= nowMs) return nowMs;
      if (next === null || boundary < next) next = boundary;
    }
    return next;
  }

  priceFor(
    symbol: string,
    snapshotLastPrice: number | null | undefined,
    analysisPrice: number | null | undefined
  ): TickerPriceView {
    const hot = this.tickers.get(symbol);
    if (hot) {
      const cached = this.hotPriceViews.get(hot);
      if (cached) return cached;
      const view: TickerPriceView = {
        value: hot.lastPrice,
        source: "hot",
        stale: hot.stale
      };
      this.hotPriceViews.set(hot, view);
      return view;
    }
    if (isFiniteNumber(snapshotLastPrice)) {
      return { value: snapshotLastPrice, source: "snapshot", stale: false };
    }
    if (isFiniteNumber(analysisPrice)) {
      return { value: analysisPrice, source: "analysis", stale: false };
    }
    return { value: null, source: "missing", stale: false };
  }

  private applyUpdates(updates: TickerRuntimeUpdate[]) {
    for (const [symbol, lastPrice, ts] of updates) {
      this.tickers.set(symbol, { lastPrice, ts, stale: false });
    }
  }

  private setMetadata(batch: TickerRuntimeBatch) {
    this.metadata.set("sequence", batch.sequence);
    this.metadata.set("asOf", batch.asOf);
  }
}

type VisibilitySource = {
  readonly visibilityState: DocumentVisibilityState;
  addEventListener(type: "visibilitychange", listener: EventListener): void;
  removeEventListener(type: "visibilitychange", listener: EventListener): void;
};

type TickerPollControllerOptions = {
  overlay: TickerOverlay;
  fetchBatch: (afterSequence: number) => Promise<TickerRuntimeBatch | undefined>;
  visibility?: VisibilitySource;
};

type TickerPollState = {
  status: "idle" | "waiting" | "live" | "paused" | "retrying";
  lastError: string | null;
  consecutiveFailures: number;
};

export class TickerPollController {
  private readonly overlay: TickerOverlay;
  private readonly fetchBatch: TickerPollControllerOptions["fetchBatch"];
  private readonly visibility: VisibilitySource;
  private readonly state = new SvelteMap<
    keyof TickerPollState,
    TickerPollState[keyof TickerPollState]
  >([
    ["status", "idle"],
    ["lastError", null],
    ["consecutiveFailures", 0]
  ]);
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private staleTimer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  private inFlight = false;

  constructor({ overlay, fetchBatch, visibility = document }: TickerPollControllerOptions) {
    this.overlay = overlay;
    this.fetchBatch = fetchBatch;
    this.visibility = visibility;
  }

  get status() {
    return this.state.get("status") as TickerPollState["status"];
  }

  get lastError() {
    return this.state.get("lastError") as TickerPollState["lastError"];
  }

  get consecutiveFailures() {
    return this.state.get("consecutiveFailures") as TickerPollState["consecutiveFailures"];
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.visibility.addEventListener("visibilitychange", this.handleVisibilityChange);
    if (this.isVisible()) {
      void this.poll(true);
    } else {
      this.setState("status", "paused");
    }
  }

  stop() {
    if (!this.running) return;
    this.running = false;
    this.visibility.removeEventListener("visibilitychange", this.handleVisibilityChange);
    this.cancelTimers();
    this.setState("status", "idle");
  }

  private readonly handleVisibilityChange: EventListener = () => {
    if (!this.isVisible()) {
      this.cancelTimers();
      this.setState("status", "paused");
      return;
    }
    this.setState("consecutiveFailures", 0);
    this.overlay.refreshStaleness();
    this.scheduleStaleRefresh();
    void this.poll(true);
  };

  private async poll(forceFull: boolean) {
    if (!this.running || !this.isVisible() || this.inFlight) return;
    this.clearPollTimer();
    this.inFlight = true;
    try {
      const batch = await this.fetchBatch(forceFull ? 0 : this.overlay.sequence);
      if (!this.running) return;
      if (batch) {
        const result = this.overlay.applyBatch(batch);
        if (result === "gap" && this.isVisible()) {
          const full = await this.fetchBatch(0);
          if (!this.running) return;
          if (full) this.overlay.applyBatch(full);
        }
      }
      this.overlay.refreshStaleness();
      if (!this.isVisible()) {
        this.setState("status", "paused");
        return;
      }
      this.setState("consecutiveFailures", 0);
      this.setState("lastError", null);
      this.setState("status", this.overlay.sequence > 0 ? "live" : "waiting");
      this.schedulePoll(tickerPollIntervalMs);
      this.scheduleStaleRefresh();
    } catch (cause) {
      const consecutiveFailures = this.consecutiveFailures + 1;
      this.setState("consecutiveFailures", consecutiveFailures);
      this.setState(
        "lastError",
        cause instanceof Error && cause.message ? cause.message : "ticker取得失敗"
      );
      this.setState("status", "retrying");
      this.overlay.refreshStaleness();
      this.schedulePoll(tickerRetryDelayMs(consecutiveFailures));
      this.scheduleStaleRefresh();
    } finally {
      this.inFlight = false;
    }
  }

  private schedulePoll(delayMs: number) {
    if (!this.running || !this.isVisible()) return;
    this.clearPollTimer();
    this.pollTimer = setTimeout(() => void this.poll(false), delayMs);
  }

  private scheduleStaleRefresh() {
    this.clearStaleTimer();
    if (!this.running || !this.isVisible()) return;
    const nextAt = this.overlay.nextStaleAtMs();
    if (nextAt === null) return;
    this.staleTimer = setTimeout(() => {
      this.overlay.refreshStaleness();
      this.scheduleStaleRefresh();
    }, Math.max(0, nextAt - Date.now()));
  }

  private isVisible() {
    return this.visibility.visibilityState === "visible";
  }

  private cancelTimers() {
    this.clearPollTimer();
    this.clearStaleTimer();
  }

  private clearPollTimer() {
    if (this.pollTimer === null) return;
    clearTimeout(this.pollTimer);
    this.pollTimer = null;
  }

  private clearStaleTimer() {
    if (this.staleTimer === null) return;
    clearTimeout(this.staleTimer);
    this.staleTimer = null;
  }

  private setState<Key extends keyof TickerPollState>(key: Key, value: TickerPollState[Key]) {
    this.state.set(key, value);
  }
}

export function tickerRetryDelayMs(consecutiveFailures: number) {
  if (!Number.isFinite(consecutiveFailures) || consecutiveFailures <= 1) {
    return tickerPollIntervalMs;
  }
  return Math.min(
    tickerRetryMaximumMs,
    tickerPollIntervalMs * 2 ** Math.floor(consecutiveFailures - 1)
  );
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
