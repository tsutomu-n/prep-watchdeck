import { expect, test } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import {
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync
} from "node:fs";
import { resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const soakPaths = resolveWebTestStatePaths("soak");
const runtimeRoot = soakPaths.runtimeRoot;
const artifactRoot = soakPaths.artifactRoot;
const snapshotPath = soakPaths.snapshotPath;
const serviceStatePath = soakPaths.serviceStatePath;
const chartsDir = soakPaths.chartsDir;
const tickerRuntimePath = soakPaths.tickerRuntimePath;
const nativeBrowserProfileDir = resolve(runtimeRoot, "native-browser-profile");
const evidencePath = resolve(artifactRoot, "soak-evidence.json");
const soakPort = positiveInteger(process.env.SOAK_PORT, 4_175);
const appOrigin = `http://127.0.0.1:${soakPort}`;
const durationMs = positiveInteger(process.env.SOAK_DURATION_MS, 3_600_000);
const warmupMs = positiveInteger(
  process.env.SOAK_WARMUP_MS,
  durationMs >= 3_600_000 ? 300_000 : Math.max(1_000, Math.min(5_000, Math.floor(durationMs / 5)))
);
const sampleIntervalMs = positiveInteger(
  process.env.SOAK_SAMPLE_INTERVAL_MS,
  durationMs >= 3_600_000 ? 300_000 : Math.max(1_000, Math.min(5_000, Math.floor(durationMs / 5)))
);
const interactionIntervalMs = positiveInteger(
  process.env.SOAK_INTERACTION_INTERVAL_MS,
  durationMs >= 3_600_000 ? 60_000 : Math.max(1_000, Math.min(5_000, Math.floor(durationMs / 6)))
);
const coldIntervalMs = positiveInteger(process.env.SOAK_COLD_INTERVAL_MS, 60_000);
const staleIntervalMs = positiveInteger(
  process.env.SOAK_STALE_INTERVAL_MS,
  durationMs >= 3_600_000 ? 900_000 : Math.max(8_000, Math.floor(durationMs / 3))
);
const tickerIntervalMs = 1_000;
const requestDrainTimeoutMs = 5_000;

type SnapshotRow = {
  symbol: string;
  lastPrice?: number | null;
  analysisPrice?: number | null;
  category: string;
  changePctByTf?: Record<string, number>;
  turnoverUsdtByTf?: Record<string, number>;
  volumeRatioByTf?: Record<string, number>;
  [key: string]: unknown;
};

type SnapshotFixture = {
  runId: string;
  generatedAt: number;
  dataAsOf: number;
  summary: { counts: Record<string, number>; [key: string]: unknown };
  rows: SnapshotRow[];
  [key: string]: unknown;
};

type TickerUpdate = [symbol: string, lastPrice: number, ts: number];

type PageSnapshot = {
  timers: {
    activeTimeouts: number;
    activeIntervals: number;
    createdTimeouts: number;
    clearedTimeouts: number;
    firedTimeouts: number;
    createdIntervals: number;
    clearedIntervals: number;
  };
  requests: {
    started: number;
    finished: number;
    failed: number;
    inFlight: number;
    maxInFlight: number;
    byPath: Record<string, number>;
  };
  charts: { created: number; removed: number; active: number; maxActive: number };
  visibility: {
    current: DocumentVisibilityState;
    transitions: number;
    hiddenTransitions: number;
    visibleTransitions: number;
    hiddenPollRequests: number;
  };
  dom: {
    elements: number;
    marketRows: number;
    chartSurfaces: number;
    canvases: number;
    stalePrices: number;
  };
};

type SoakSample = PageSnapshot & {
  elapsedMs: number;
  sampledAt: string;
  heapUsedBytes: number;
  heapTotalBytes: number;
  requestDrainWaitMs: number;
};

type UnsettledSoakSample = Omit<SoakSample, "requestDrainWaitMs">;

type StaleSample = {
  elapsedMs: number;
  staleCount: number;
  recoveredCount: number;
};

type SymbolCycle = {
  elapsedMs: number;
  symbol: string;
  chartActive: number;
  chartCreated: number;
  chartSurfaces: number;
  targetsAfterClose: number;
};

type SoakEvidence = {
  startedAt: string;
  endedAt: string;
  durationMs: number;
  elapsedMs: number;
  warmupMs: number;
  sampleIntervalMs: number;
  tickerIntervalMs: number;
  coldIntervalMs: number;
  interactionIntervalMs: number;
  samples: SoakSample[];
  staleSamples: StaleSample[];
  symbolCycles: SymbolCycle[];
  interactionCount: number;
  producer: { tickerWrites: number; coldWrites: number; finalSequence: number };
};

test("one-hour realtime Dashboard soak stays bounded", async () => {
  const fixture = generate400SymbolFixture();
  const tickerProducer = new TickerProducer(fixture.rows);
  const coldProducer = new ColdProducer(fixture, fixture.rows[0].symbol);
  tickerProducer.start();
  coldProducer.start();

  mkdirSync(nativeBrowserProfileDir, { recursive: true });
  const chrome = spawn(
    "/usr/bin/google-chrome",
    [
      "--remote-debugging-port=0",
      `--user-data-dir=${nativeBrowserProfileDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-background-networking",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "about:blank"
    ],
    {
      stdio: "ignore",
      env: {
        ...process.env,
        HOME: runtimeRoot,
        XDG_CONFIG_HOME: resolve(runtimeRoot, "native-config")
      }
    }
  );

  const samples: SoakSample[] = [];
  const staleSamples: StaleSample[] = [];
  const symbolCycles: SymbolCycle[] = [];
  let interactionCount = 0;
  let startedAt = 0;

  try {
    const devtoolsPort = await readDevtoolsPort(chrome);
    const mainTarget = await waitForTarget(devtoolsPort, (target) => target.type === "page");
    const client = await CdpClient.connect(mainTarget.webSocketDebuggerUrl);
    await client.send("Page.enable");
    await client.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `(${installSoakInstrumentation.toString()})()`
    });
    await client.send("Page.navigate", { url: appOrigin });
    await waitForDashboard(client);
    await exerciseDashboard(client, 0);
    await waitUntil(
      async () => (await pageSnapshot(client)).charts.active === 1,
      15_000,
      "Dashboard chart instance instrumentation did not activate"
    );
    client.close();

    startedAt = Date.now();
    const endAt = startedAt + durationMs;
    let nextSampleAt = startedAt + warmupMs;
    let nextInteractionAt = startedAt + interactionIntervalMs;
    let nextStaleAt = startedAt + staleIntervalMs;
    let sampleIndex = 0;

    while (Date.now() < endAt) {
      const nextEventAt = Math.min(nextSampleAt, nextInteractionAt, nextStaleAt, endAt);
      await delay(Math.min(1_000, Math.max(0, nextEventAt - Date.now())));
      const now = Date.now();

      if (now >= nextInteractionAt && nextInteractionAt < endAt) {
        const interactionClient = await mainClient(devtoolsPort, mainTarget.id);
        await exerciseDashboard(interactionClient, interactionCount + 1);
        interactionClient.close();
        await exerciseRealVisibility();
        interactionCount += 1;
        nextInteractionAt += interactionIntervalMs;
      }

      if (now >= nextStaleAt && nextStaleAt < endAt - 8_000) {
        tickerProducer.pauseFor(6_500);
        await delay(5_800);
        const staleClient = await mainClient(devtoolsPort, mainTarget.id);
        const staleCount = (await pageSnapshot(staleClient)).dom.stalePrices;
        staleClient.close();
        await waitUntil(async () => {
          const recoveryClient = await mainClient(devtoolsPort, mainTarget.id);
          const recovered = (await pageSnapshot(recoveryClient)).dom.stalePrices;
          recoveryClient.close();
          return recovered === 0;
        }, 8_000, "stale prices did not recover after producer resumed");
        staleSamples.push({
          elapsedMs: Date.now() - startedAt,
          staleCount,
          recoveredCount: 0
        });
        nextStaleAt += staleIntervalMs;
      }

      if (now >= nextSampleAt && nextSampleAt <= endAt) {
        const sample = await collectSettledSample(devtoolsPort, mainTarget.id, startedAt);
        samples.push(sample);
        sampleIndex += 1;
        if (sampleIndex % 2 === 0) {
          symbolCycles.push(
            await exerciseSymbolPage(devtoolsPort, mainTarget.id, fixture.rows[sampleIndex % fixture.rows.length].symbol, startedAt)
          );
        }
        console.log(`SOAK_PROGRESS ${JSON.stringify(sample)}`);
        nextSampleAt += sampleIntervalMs;
      }
    }

    if (samples.length === 0 || samples.at(-1)!.elapsedMs < durationMs - 1_000) {
      samples.push(await collectSettledSample(devtoolsPort, mainTarget.id, startedAt));
    }

    const evidence: SoakEvidence = {
      startedAt: new Date(startedAt).toISOString(),
      endedAt: new Date().toISOString(),
      durationMs,
      elapsedMs: Date.now() - startedAt,
      warmupMs,
      sampleIntervalMs,
      tickerIntervalMs,
      coldIntervalMs,
      interactionIntervalMs,
      samples,
      staleSamples,
      symbolCycles,
      interactionCount,
      producer: {
        tickerWrites: tickerProducer.writeCount,
        coldWrites: coldProducer.writeCount,
        finalSequence: tickerProducer.sequence
      }
    };
    writeJsonAtomically(evidencePath, evidence);
    console.log(`SOAK_EVIDENCE ${JSON.stringify(evidence)}`);
    assertSoakEvidence(evidence);
  } finally {
    tickerProducer.stop();
    coldProducer.stop();
    await stopChild(chrome);
  }
});

class TickerProducer {
  sequence = 1;
  writeCount = 0;
  private currentFull: TickerUpdate[];
  private timer: ReturnType<typeof setInterval> | null = null;
  private pausedUntil = 0;

  constructor(private readonly rows: SnapshotRow[]) {
    const now = Date.now();
    this.currentFull = rows.map((row, index) => [row.symbol, positiveNumber(row.lastPrice, 100 + index), now]);
    this.publish([]);
  }

  start() {
    this.timer = setInterval(() => {
      if (Date.now() < this.pausedUntil) return;
      this.sequence += 1;
      const now = Date.now();
      const updates: TickerUpdate[] = this.currentFull.map(([symbol, lastPrice], index) => [
        symbol,
        lastPrice + ((this.sequence + index) % 2 === 0 ? 0.01 : -0.01),
        now
      ]);
      this.currentFull = updates;
      this.publish(updates);
    }, tickerIntervalMs);
  }

  pauseFor(milliseconds: number) {
    this.pausedUntil = Math.max(this.pausedUntil, Date.now() + milliseconds);
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  private publish(deltaUpdates: TickerUpdate[]) {
    writeJsonAtomically(tickerRuntimePath, {
      schemaVersion: 1,
      sequence: this.sequence,
      asOf: Math.max(...this.currentFull.map((update) => update[2])),
      fullUpdates: this.currentFull,
      deltaUpdates
    });
    this.writeCount += 1;
  }
}

class ColdProducer {
  writeCount = 0;
  private generation = 0;
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private readonly snapshot: SnapshotFixture,
    private readonly chartSymbol: string
  ) {
    this.publish();
  }

  start() {
    this.timer = setInterval(() => this.publish(), coldIntervalMs);
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  private publish() {
    const now = Date.now();
    const runId = `soak-400-${this.generation}`;
    writeDetailChartFixture(runId, this.chartSymbol, now);
    writeServiceState(now);
    writeJsonAtomically(snapshotPath, {
      ...this.snapshot,
      runId,
      generatedAt: now,
      dataAsOf: now
    });
    this.generation += 1;
    this.writeCount += 1;
  }
}

async function collectSettledSample(
  port: number,
  targetId: string,
  startedAt: number
): Promise<SoakSample> {
  const drainStartedAt = Date.now();
  let sample = await collectSample(port, targetId, startedAt);
  while (sample.requests.inFlight !== 0) {
    if (Date.now() - drainStartedAt >= requestDrainTimeoutMs) {
      throw new Error(
        `Dashboard requests did not drain within ${requestDrainTimeoutMs}ms: ` +
          `${sample.requests.inFlight} in flight, ` +
          `${sample.requests.started} started, ${sample.requests.finished} finished`
      );
    }
    await delay(50);
    sample = await collectSample(port, targetId, startedAt);
  }
  return {
    ...sample,
    requestDrainWaitMs: Date.now() - drainStartedAt
  };
}

async function collectSample(
  port: number,
  targetId: string,
  startedAt: number
): Promise<UnsettledSoakSample> {
  const client = await mainClient(port, targetId);
  try {
    await client.send("HeapProfiler.enable");
    await client.send("HeapProfiler.collectGarbage");
    const heap = await client.send<{ usedSize: number; totalSize: number }>("Runtime.getHeapUsage");
    const snapshot = await pageSnapshot(client);
    return {
      elapsedMs: Date.now() - startedAt,
      sampledAt: new Date().toISOString(),
      heapUsedBytes: heap.usedSize,
      heapTotalBytes: heap.totalSize,
      ...snapshot
    };
  } finally {
    client.close();
  }
}

async function exerciseDashboard(client: CdpClient, iteration: number) {
  await evaluate<void>(
    client,
    `(async () => {
      const group = document.querySelector('[role="group"][aria-label="時間軸ショートカット"]');
      const timeframe = ${iteration % 2 === 0 ? JSON.stringify("1h") : JSON.stringify("15m")};
      const button = Array.from(group?.querySelectorAll('button') ?? [])
        .find((candidate) => candidate.textContent?.trim() === timeframe);
      if (!(button instanceof HTMLButtonElement)) throw new Error('Common timeframe control missing');
      button.click();
      const details = document.querySelector('details[data-detail-group="context"]');
      const summary = details?.querySelector('summary');
      if (!details || !summary) throw new Error('context details missing');
      if (!details.open) summary.click();
      else {
        summary.click();
        await new Promise((resolve) => setTimeout(resolve, 50));
        summary.click();
      }
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    })()`
  );
}

async function exerciseRealVisibility() {
  execFileSync(
    "xdotool",
    ["search", "--name", "準備監視板", "windowactivate", "--sync", "key", "ctrl+t"],
    { stdio: "pipe" }
  );
  await delay(2_200);
  execFileSync("xdotool", ["getactivewindow", "key", "ctrl+w"], { stdio: "pipe" });
  await delay(300);
}

async function exerciseSymbolPage(
  port: number,
  mainTargetId: string,
  symbol: string,
  startedAt: number
): Promise<SymbolCycle> {
  const main = await mainClient(port, mainTargetId);
  const created = await main.send<{ targetId: string }>("Target.createTarget", {
    url: "about:blank",
    background: true
  });
  main.close();
  const target = await waitForTarget(port, (candidate) => candidate.id === created.targetId);
  const client = await CdpClient.connect(target.webSocketDebuggerUrl);
  try {
    await client.send("Page.enable");
    await client.send("Page.addScriptToEvaluateOnNewDocument", {
      source: `(${installSoakInstrumentation.toString()})()`
    });
    await client.send("Page.navigate", { url: `${appOrigin}/symbols/${encodeURIComponent(symbol)}?tf=15m` });
    await waitUntil(async () => {
      const snapshot = await pageSnapshot(client).catch(() => null);
      return snapshot?.charts.active === 1 && snapshot.dom.chartSurfaces === 1;
    }, 15_000, `symbol chart did not load for ${symbol}`);
    const snapshot = await pageSnapshot(client);
    return {
      elapsedMs: Date.now() - startedAt,
      symbol,
      chartActive: snapshot.charts.active,
      chartCreated: snapshot.charts.created,
      chartSurfaces: snapshot.dom.chartSurfaces,
      targetsAfterClose: await closeTargetAndCount(port, mainTargetId, created.targetId)
    };
  } finally {
    client.close();
  }
}

async function closeTargetAndCount(port: number, mainTargetId: string, targetId: string) {
  const main = await mainClient(port, mainTargetId);
  try {
    await main.send("Target.closeTarget", { targetId });
  } finally {
    main.close();
  }
  await waitUntil(
    async () => !(await listTargets(port)).some((target) => target.id === targetId),
    5_000,
    `symbol target ${targetId} did not close`
  );
  return (await listTargets(port)).filter((target) => target.type === "page").length;
}

function assertSoakEvidence(evidence: SoakEvidence) {
  expect(evidence.elapsedMs, "soak elapsed real time").toBeGreaterThanOrEqual(evidence.durationMs);
  expect(evidence.samples.length, "periodic samples").toBeGreaterThanOrEqual(2);
  const baseline = evidence.samples[0];
  const heapLimit = baseline.heapUsedBytes * 1.2;
  for (const sample of evidence.samples) {
    expect.soft(sample.heapUsedBytes, `heap at ${sample.elapsedMs}ms`).toBeLessThanOrEqual(heapLimit);
    expect.soft(sample.dom.marketRows, `market rows at ${sample.elapsedMs}ms`).toBe(400);
    expect.soft(sample.dom.chartSurfaces, `chart surfaces at ${sample.elapsedMs}ms`).toBe(1);
    expect.soft(sample.charts.active, `active charts at ${sample.elapsedMs}ms`).toBe(1);
    expect.soft(sample.charts.maxActive, `maximum charts at ${sample.elapsedMs}ms`).toBe(1);
    expect.soft(sample.charts.created, `created charts at ${sample.elapsedMs}ms`).toBe(1);
    expect.soft(sample.requests.failed, `failed fetches at ${sample.elapsedMs}ms`).toBe(0);
    expect.soft(sample.requests.inFlight, `outstanding fetches at ${sample.elapsedMs}ms`).toBe(0);
    expect.soft(sample.requestDrainWaitMs, `request drain at ${sample.elapsedMs}ms`).toBeLessThanOrEqual(
      requestDrainTimeoutMs
    );
    expect.soft(sample.requests.maxInFlight, `maximum concurrent fetches at ${sample.elapsedMs}ms`).toBeLessThanOrEqual(2);
    expect.soft(sample.visibility.hiddenPollRequests, `hidden polls at ${sample.elapsedMs}ms`).toBe(0);
    expect.soft(sample.timers.activeIntervals, `intervals at ${sample.elapsedMs}ms`).toBe(baseline.timers.activeIntervals);
    expect.soft(sample.timers.activeTimeouts, `timeouts at ${sample.elapsedMs}ms`).toBeLessThanOrEqual(
      baseline.timers.activeTimeouts + 2
    );
    expect.soft(sample.dom.elements, `DOM elements at ${sample.elapsedMs}ms`).toBeLessThanOrEqual(
      baseline.dom.elements + 5
    );
  }
  expect(evidence.staleSamples.length, "stale/recovery samples").toBeGreaterThan(0);
  for (const stale of evidence.staleSamples) {
    expect.soft(stale.staleCount, `stale display at ${stale.elapsedMs}ms`).toBeGreaterThan(0);
    expect.soft(stale.recoveredCount, `stale recovery at ${stale.elapsedMs}ms`).toBe(0);
  }
  for (const cycle of evidence.symbolCycles) {
    expect.soft(cycle.chartActive, `symbol chart active for ${cycle.symbol}`).toBe(1);
    expect.soft(cycle.chartCreated, `symbol chart created for ${cycle.symbol}`).toBe(1);
    expect.soft(cycle.chartSurfaces, `symbol chart DOM for ${cycle.symbol}`).toBe(1);
    expect.soft(cycle.targetsAfterClose, `browser targets after ${cycle.symbol}`).toBe(1);
  }
}

function installSoakInstrumentation() {
  const originalSetTimeout = window.setTimeout.bind(window);
  const originalClearTimeout = window.clearTimeout.bind(window);
  const originalSetInterval = window.setInterval.bind(window);
  const originalClearInterval = window.clearInterval.bind(window);
  const timeoutIds = new Set<number>();
  const intervalIds = new Set<number>();
  const timers = {
    createdTimeouts: 0,
    clearedTimeouts: 0,
    firedTimeouts: 0,
    createdIntervals: 0,
    clearedIntervals: 0
  };
  window.setTimeout = ((handler: TimerHandler, timeout?: number, ...argumentsList: unknown[]) => {
    let id = 0;
    const wrapped = typeof handler === "function"
      ? (...callbackArguments: unknown[]) => {
          timeoutIds.delete(id);
          timers.firedTimeouts += 1;
          return handler(...callbackArguments);
        }
      : handler;
    id = originalSetTimeout(wrapped, timeout, ...argumentsList);
    timeoutIds.add(id);
    timers.createdTimeouts += 1;
    return id;
  }) as typeof window.setTimeout;
  window.clearTimeout = ((id?: number) => {
    if (typeof id === "number" && timeoutIds.delete(id)) timers.clearedTimeouts += 1;
    originalClearTimeout(id);
  }) as typeof window.clearTimeout;
  window.setInterval = ((handler: TimerHandler, timeout?: number, ...argumentsList: unknown[]) => {
    const id = originalSetInterval(handler, timeout, ...argumentsList);
    intervalIds.add(id);
    timers.createdIntervals += 1;
    return id;
  }) as typeof window.setInterval;
  window.clearInterval = ((id?: number) => {
    if (typeof id === "number" && intervalIds.delete(id)) timers.clearedIntervals += 1;
    originalClearInterval(id);
  }) as typeof window.clearInterval;

  const requests = {
    started: 0,
    finished: 0,
    failed: 0,
    inFlight: 0,
    maxInFlight: 0,
    byPath: {} as Record<string, number>
  };
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...argumentsList) => {
    const input = argumentsList[0];
    const url = new URL(
      typeof input === "string" || input instanceof URL ? String(input) : input.url,
      window.location.href
    );
    requests.started += 1;
    requests.inFlight += 1;
    requests.maxInFlight = Math.max(requests.maxInFlight, requests.inFlight);
    requests.byPath[url.pathname] = (requests.byPath[url.pathname] ?? 0) + 1;
    try {
      const response = await originalFetch(...argumentsList);
      requests.finished += 1;
      return response;
    } catch (cause) {
      requests.failed += 1;
      throw cause;
    } finally {
      requests.inFlight -= 1;
    }
  };

  const charts = { created: 0, removed: 0, active: 0, maxActive: 0 };
  const visibility = {
    current: document.visibilityState,
    transitions: 0,
    hiddenTransitions: 0,
    visibleTransitions: 0,
    hiddenPollRequests: 0,
    hiddenTickerBaseline: null as number | null
  };
  document.addEventListener("visibilitychange", () => {
    visibility.current = document.visibilityState;
    visibility.transitions += 1;
    if (document.visibilityState === "hidden") {
      visibility.hiddenTransitions += 1;
      visibility.hiddenTickerBaseline = requests.byPath["/api/runtime/tickers"] ?? 0;
    } else {
      visibility.visibleTransitions += 1;
      if (visibility.hiddenTickerBaseline !== null) {
        visibility.hiddenPollRequests +=
          (requests.byPath["/api/runtime/tickers"] ?? 0) - visibility.hiddenTickerBaseline;
      }
      visibility.hiddenTickerBaseline = null;
    }
  });

  const state = { timeoutIds, intervalIds, timers, requests, charts, visibility };
  Object.defineProperty(window, "__watchdeckSoak", { value: state, configurable: false });
  Object.defineProperty(window, "__watchdeckInstrumentation", {
    value: {
      chartCreated() {
        charts.created += 1;
        charts.active += 1;
        charts.maxActive = Math.max(charts.maxActive, charts.active);
      },
      chartRemoved() {
        charts.removed += 1;
        charts.active -= 1;
      }
    },
    configurable: false
  });
}

async function pageSnapshot(client: CdpClient): Promise<PageSnapshot> {
  return evaluate<PageSnapshot>(
    client,
    `(() => {
      const state = window.__watchdeckSoak;
      if (!state) throw new Error('soak instrumentation missing');
      return {
        timers: {
          activeTimeouts: state.timeoutIds.size,
          activeIntervals: state.intervalIds.size,
          ...state.timers
        },
        requests: structuredClone(state.requests),
        charts: structuredClone(state.charts),
        visibility: {
          current: state.visibility.current,
          transitions: state.visibility.transitions,
          hiddenTransitions: state.visibility.hiddenTransitions,
          visibleTransitions: state.visibility.visibleTransitions,
          hiddenPollRequests: state.visibility.hiddenPollRequests
        },
        dom: {
          elements: document.querySelectorAll('*').length,
          marketRows: document.querySelectorAll('[data-market-row][data-symbol]').length,
          chartSurfaces: document.querySelectorAll('.chart-surface').length,
          canvases: document.querySelectorAll('canvas').length,
          stalePrices: document.querySelectorAll('.current-price.stale').length
        }
      };
    })()`
  );
}

async function waitForDashboard(client: CdpClient) {
  await waitUntil(async () => {
    return evaluate<boolean>(
      client,
      `document.querySelectorAll('[data-market-row][data-symbol]').length === 400 &&
       document.body.textContent.includes('HOT LIVE')`
    ).catch(() => false);
  }, 20_000, "400-row Dashboard did not become ready");
}

function generate400SymbolFixture() {
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8")) as SnapshotFixture;
  const originalRows = snapshot.rows.map((row) => structuredClone(row));
  if (originalRows.length !== 5) throw new Error(`basic fixture row count changed: ${originalRows.length}`);
  const addedRows = Array.from({ length: 395 }, (_, index): SnapshotRow => {
    const base = structuredClone(originalRows[index % originalRows.length]);
    const offset = (index + 1) / 1_000;
    return {
      ...base,
      symbol: `SOAK${String(index + 1).padStart(4, "0")}USDT`,
      lastPrice: positiveNumber(base.lastPrice, 10) + offset,
      analysisPrice: positiveNumber(base.analysisPrice, 10) + offset,
      changePctByTf: offsetRecord(base.changePctByTf, offset),
      turnoverUsdtByTf: offsetRecord(base.turnoverUsdtByTf, index + 1),
      volumeRatioByTf: offsetRecord(base.volumeRatioByTf, offset)
    };
  });
  const fixture: SnapshotFixture = {
    ...snapshot,
    runId: "soak-400-0",
    generatedAt: Date.now(),
    dataAsOf: Date.now(),
    rows: [...originalRows, ...addedRows],
    summary: {
      ...snapshot.summary,
      serviceSource: "duckdb-service",
      counts: countCategories([...originalRows, ...addedRows])
    }
  };
  return fixture;
}

function writeDetailChartFixture(snapshotRunId: string, symbol: string, now: number) {
  const timeframes = Object.fromEntries(
    ["5m", "15m", "1h", "4h", "24h", "74h"].map((timeframe, timeframeIndex) => [
      timeframe,
      Array.from({ length: 128 }, (_, index) => ({
        ts: 1_700_000_000_000 + timeframeIndex * 100_000_000 + index * 300_000,
        open: 100 + index / 100,
        high: 101 + index / 100,
        low: 99 + index / 100,
        close: 100.5 + index / 100,
        quoteVolume: 1_000 + index
      }))
    ])
  );
  writeJsonAtomically(resolve(chartsDir, `${symbol}.json`), {
    schemaVersion: 2,
    snapshotRunId,
    symbol,
    generatedAt: now,
    dataAsOf: now,
    timeframes
  });
}

function writeServiceState(now: number) {
  writeJsonAtomically(serviceStatePath, {
    schemaVersion: 1,
    generatedAtMs: now,
    dataAsOfMs: now,
    productType: "USDT-FUTURES",
    streamSymbols: 400,
    streamChannels: 2,
    streamShards: 1,
    diagnostics: { tickerCount: 400, candle1mCount: 400, latestCandle1mTsMs: now }
  });
}

function writeJsonAtomically(path: string, value: unknown) {
  mkdirSync(resolve(path, ".."), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify(value)}\n`, "utf-8");
  renameSync(temporaryPath, path);
}

function countCategories(rows: SnapshotRow[]) {
  return rows.reduce<Record<string, number>>((counts, row) => {
    counts[row.category] = (counts[row.category] ?? 0) + 1;
    return counts;
  }, {});
}

function offsetRecord(source: Record<string, number> | undefined, offset: number) {
  return Object.fromEntries(Object.entries(source ?? {}).map(([key, value]) => [key, value + offset]));
}

function positiveNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

type TargetInfo = { id: string; type: string; url: string; webSocketDebuggerUrl: string };

async function listTargets(port: number): Promise<TargetInfo[]> {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  if (!response.ok) throw new Error(`target list failed: ${response.status}`);
  return (await response.json()) as TargetInfo[];
}

async function waitForTarget(port: number, predicate: (target: TargetInfo) => boolean) {
  let match: TargetInfo | undefined;
  await waitUntil(async () => {
    match = (await listTargets(port)).find(predicate);
    return match !== undefined;
  }, 10_000, "Chrome target unavailable");
  if (!match) throw new Error("Chrome target unavailable");
  return match;
}

async function mainClient(port: number, targetId: string) {
  const target = await waitForTarget(port, (candidate) => candidate.id === targetId);
  return CdpClient.connect(target.webSocketDebuggerUrl);
}

async function readDevtoolsPort(chrome: ChildProcess) {
  const path = resolve(nativeBrowserProfileDir, "DevToolsActivePort");
  let port = 0;
  await waitUntil(() => {
    if (chrome.exitCode !== null) throw new Error(`native Chrome exited with ${chrome.exitCode}`);
    try {
      port = Number(readFileSync(path, "utf-8").split(/\r?\n/, 1)[0]);
      return Number.isSafeInteger(port) && port > 0;
    } catch {
      return false;
    }
  }, 10_000, "native Chrome DevTools port unavailable");
  return port;
}

class CdpClient {
  private nextId = 1;
  private readonly pending = new Map<
    number,
    { resolve: (value: unknown) => void; reject: (cause: Error) => void }
  >();

  private constructor(private readonly socket: WebSocket) {
    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(String(event.data)) as {
        id?: number;
        result?: unknown;
        error?: { message?: string };
      };
      if (payload.id === undefined) return;
      const waiter = this.pending.get(payload.id);
      if (!waiter) return;
      this.pending.delete(payload.id);
      if (payload.error) waiter.reject(new Error(payload.error.message ?? "CDP command failed"));
      else waiter.resolve(payload.result);
    });
  }

  static async connect(url: string) {
    const socket = new WebSocket(url);
    await new Promise<void>((resolveOpen, rejectOpen) => {
      socket.addEventListener("open", () => resolveOpen(), { once: true });
      socket.addEventListener("error", () => rejectOpen(new Error("CDP connection failed")), { once: true });
    });
    return new CdpClient(socket);
  }

  send<T = Record<string, unknown>>(method: string, params: Record<string, unknown> = {}) {
    const id = this.nextId;
    this.nextId += 1;
    const response = new Promise<T>((resolveResponse, rejectResponse) => {
      this.pending.set(id, {
        resolve: (value) => resolveResponse(value as T),
        reject: rejectResponse
      });
    });
    this.socket.send(JSON.stringify({ id, method, params }));
    return response;
  }

  close() {
    this.socket.close();
    for (const waiter of this.pending.values()) waiter.reject(new Error("CDP connection closed"));
    this.pending.clear();
  }
}

async function evaluate<T>(client: CdpClient, expression: string): Promise<T> {
  const response = await client.send<{
    result: { value?: T };
    exceptionDetails?: { text?: string; exception?: { description?: string } };
  }>("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) {
    throw new Error(
      response.exceptionDetails.exception?.description ?? response.exceptionDetails.text ?? "Runtime.evaluate failed"
    );
  }
  return response.result.value as T;
}

async function waitUntil(
  predicate: () => boolean | Promise<boolean>,
  timeoutMs: number,
  message: string
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await delay(50);
  }
  throw new Error(message);
}

function delay(milliseconds: number) {
  return new Promise<void>((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

async function stopChild(child: ChildProcess) {
  if (child.exitCode !== null) return;
  child.kill("SIGTERM");
  await Promise.race([
    new Promise<void>((resolveExit) => child.once("exit", () => resolveExit())),
    delay(3_000)
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}

function positiveInteger(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}
