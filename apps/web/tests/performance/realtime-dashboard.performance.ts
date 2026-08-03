import { expect, test, type Page } from "@playwright/test";
import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { createServer, type IncomingMessage, type Server } from "node:http";
import { gzipSync } from "node:zlib";
import {
  mkdirSync,
  readFileSync,
  readdirSync,
  renameSync,
  statSync,
  writeFileSync
} from "node:fs";
import { resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const performancePaths = resolveWebTestStatePaths("performance");
const performanceRoot = performancePaths.runtimeRoot;
const snapshotPath = performancePaths.snapshotPath;
const serviceStatePath = performancePaths.serviceStatePath;
const chartsDir = performancePaths.chartsDir;
const tickerRuntimePath = performancePaths.tickerRuntimePath;
const nativeBrowserProfileDir = resolve(performanceRoot, "native-browser-profile");
const clientManifestPath = resolve(process.cwd(), ".svelte-kit/output/client/.vite/manifest.json");
const fixedNow = 4_102_444_800_000;
const hotSampleCount = 20;
const rawSortSampleCount = 20;

const budgets = {
  latestRawBytes: 2_000_000,
  latestGzipBytes: 400_000,
  rootHtmlRawBytes: 1_500_000,
  rootHtmlGzipBytes: 350_000,
  tickerFullBytes: 100_000,
  tickerDeltaP95Bytes: 50_000,
  initialChartChunkBytes: 0,
  miniBarsPerTimeframe: 16,
  detailBarsPerTimeframe: 128,
  coldLongTaskMaxMs: 100,
  coldApplyMs: 200,
  hotLongTasksOver50Ms: 0,
  hotApplyP95Ms: 8,
  rawSortWarmupMaxMs: 100,
  rawSortP95Ms: 50,
  hiddenPollRequests: 0
} as const;

type SnapshotRow = {
  symbol: string;
  lastPrice?: number | null;
  analysisPrice?: number | null;
  category: string;
  changePctByTf?: Record<string, number>;
  turnoverUsdtByTf?: Record<string, number>;
  volumeRatioByTf?: Record<string, number>;
  sparkline?: {
    points?: unknown[];
    bars?: unknown[];
    timeframes?: Record<string, unknown[]>;
  } | null;
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

type BrowserMetrics = {
  longTasks: Array<{ startTime: number; duration: number }>;
  hotFetchEnds: number[];
  hotApplyDurations: number[];
  hotConsumedResponses: number;
  coldFetchEnds: number[];
  coldApplyDurations: number[];
  coldConsumedResponses: number;
};

type PerformanceEvidence = {
  latestRawBytes?: number;
  latestGzipBytes?: number;
  rootHtmlRawBytes?: number;
  rootHtmlGzipBytes?: number;
  tickerFullBytes?: number;
  tickerDeltaP95Bytes?: number;
  tickerDeltaBytes?: number[];
  initialChartChunkBytes?: number;
  maxMiniBars?: number;
  maxDetailBars?: number;
  coldLongTasksOver50Ms?: number;
  coldLongTaskDurationsMs?: number[];
  coldLongTaskMaxMs?: number;
  coldApplyMs?: number;
  hotLongTasksOver50Ms?: number;
  hotApplyP95Ms?: number;
  hotApplyDurationsMs?: number[];
  rawSortWarmupMaxMs?: number;
  rawSortWarmupDurationsMs?: number[];
  rawSortP95Ms?: number;
  rawSortDurationsMs?: number[];
  hiddenPollRequests?: number;
  hiddenState?: DocumentVisibilityState;
  visibleStateAfterRestore?: DocumentVisibilityState;
};

type NativeVisibilityEvent = {
  state: DocumentVisibilityState;
  at: number;
};

test.describe.configure({ mode: "serial" });

let rows: SnapshotRow[] = [];
let fullUpdates: TickerUpdate[] = [];

test.beforeAll(() => {
  rows = generate400SymbolFixture();
  fullUpdates = tickerUpdates(rows, fixedNow);
  writeTickerRuntime(1, fullUpdates, []);
  writeServiceState();
  writeDetailChartFixture("performance-400-v1", rows[0].symbol);
});

test("400-symbol production payloads stay inside the transport budgets", async ({ request }) => {
  const evidence: PerformanceEvidence = {};
  const snapshotRaw = readFileSync(snapshotPath);
  evidence.latestRawBytes = snapshotRaw.byteLength;
  evidence.latestGzipBytes = gzipSync(snapshotRaw).byteLength;
  evidence.maxMiniBars = maximumEmbeddedBarCount(JSON.parse(snapshotRaw.toString()) as SnapshotFixture);
  evidence.maxDetailBars = maximumDetailBarCount();

  const rootResponse = await request.get("/", { headers: { "accept-encoding": "identity" } });
  expect(rootResponse.ok()).toBe(true);
  const rootHtml = await rootResponse.body();
  evidence.rootHtmlRawBytes = rootHtml.byteLength;
  evidence.rootHtmlGzipBytes = gzipSync(rootHtml).byteLength;

  const fullResponse = await request.get("/api/runtime/tickers?after=0", {
    headers: { "accept-encoding": "identity" }
  });
  expect(fullResponse.ok()).toBe(true);
  evidence.tickerFullBytes = (await fullResponse.body()).byteLength;

  const deltaBytes: number[] = [];
  let currentFull = fullUpdates;
  for (let sequence = 2; sequence <= 21; sequence += 1) {
    const update: TickerUpdate = [rows[sequence % rows.length].symbol, 10_000 + sequence, fixedNow + sequence];
    currentFull = replaceTicker(currentFull, update);
    writeTickerRuntime(sequence, currentFull, [update]);
    const response = await request.get(`/api/runtime/tickers?after=${sequence - 1}`, {
      headers: { "accept-encoding": "identity" }
    });
    expect(response.ok()).toBe(true);
    deltaBytes.push((await response.body()).byteLength);
  }
  evidence.tickerDeltaBytes = deltaBytes;
  evidence.tickerDeltaP95Bytes = percentile95(deltaBytes);

  emitEvidence("transport", evidence);
  expect.soft(evidence.latestRawBytes, "thin latest.json bytes").toBeLessThanOrEqual(budgets.latestRawBytes);
  expect.soft(evidence.latestGzipBytes, "thin latest.json gzip bytes").toBeLessThanOrEqual(budgets.latestGzipBytes);
  expect.soft(evidence.rootHtmlRawBytes, "root SSR HTML bytes").toBeLessThanOrEqual(budgets.rootHtmlRawBytes);
  expect.soft(evidence.rootHtmlGzipBytes, "root SSR HTML gzip bytes").toBeLessThanOrEqual(budgets.rootHtmlGzipBytes);
  expect.soft(evidence.tickerFullBytes, "Hot ticker full payload bytes").toBeLessThanOrEqual(budgets.tickerFullBytes);
  expect.soft(evidence.tickerDeltaP95Bytes, "Hot ticker delta p95 bytes").toBeLessThanOrEqual(budgets.tickerDeltaP95Bytes);
  expect.soft(evidence.maxMiniBars, "snapshot embedded bars per timeframe").toBeLessThanOrEqual(budgets.miniBarsPerTimeframe);
  expect.soft(evidence.maxDetailBars, "detail chart bars per timeframe").toBeLessThanOrEqual(budgets.detailBarsPerTimeframe);
});

test("400-symbol production browser stays inside interaction budgets", async ({ page }) => {
  const evidence: PerformanceEvidence = {};
  fullUpdates = tickerUpdates(rows, fixedNow + 100);
  writeTickerRuntime(100, fullUpdates, []);
  await installBrowserInstrumentation(page);

  const initialScriptPaths: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.resourceType() === "script") initialScriptPaths.push(url.pathname);
  });

  await page.goto("/");
  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(watchlist.getByText("表示 400 / 全 400")).toBeVisible();
  await expect(watchlist.getByText("HOT LIVE")).toBeVisible();

  const chartChunkPath = productionChartChunkPath();
  evidence.initialChartChunkBytes = initialScriptPaths.includes(chartChunkPath) ? statSync(resolve(process.cwd(), `.svelte-kit/output/client${chartChunkPath}`)).size : 0;

  const altPrice = watchlist.locator(
    '[data-market-row][data-symbol="ALTUSDT"] .current-price'
  );
  await altPrice.scrollIntoViewIfNeeded();
  await expect(altPrice).not.toHaveText("");
  await attachPriceMutationObserver(page, altPrice.locator("span").first());
  const hotWindowStart = await page.evaluate(() => performance.now());
  for (let sequence = 101; sequence <= 100 + hotSampleCount; sequence += 1) {
    const previousText = await altPrice.innerText();
    const update: TickerUpdate = ["ALTUSDT", 20_000 + sequence, fixedNow + sequence];
    fullUpdates = replaceTicker(fullUpdates, update);
    writeTickerRuntime(sequence, fullUpdates, [update]);
    await expect.poll(() => altPrice.innerText()).not.toBe(previousText);
    await expect.poll(() => browserMetrics(page).then((metrics) => metrics.hotApplyDurations.length)).toBe(sequence - 100);
  }
  const hotWindowEnd = await page.evaluate(() => performance.now());
  const afterHot = await browserMetrics(page);
  const hotLongTasks = longTasksInWindow(afterHot.longTasks, hotWindowStart, hotWindowEnd);
  evidence.hotLongTasksOver50Ms = hotLongTasks.length;
  evidence.hotApplyDurationsMs = afterHot.hotApplyDurations;
  evidence.hotApplyP95Ms = percentile95(afterHot.hotApplyDurations);

  const rawSortEvidence = await measureRawSort(page, rawSortSampleCount);
  evidence.rawSortWarmupDurationsMs = rawSortEvidence.warmupDurationsMs;
  evidence.rawSortWarmupMaxMs = maximumOrZero(rawSortEvidence.warmupDurationsMs);
  evidence.rawSortDurationsMs = rawSortEvidence.sampleDurationsMs;
  evidence.rawSortP95Ms = percentile95(evidence.rawSortDurationsMs);

  const visibility = await measureNativeVisibilityAndPolling();
  evidence.hiddenState = visibility.hiddenState;
  evidence.visibleStateAfterRestore = visibility.visibleStateAfterRestore;
  evidence.hiddenPollRequests = visibility.hiddenPollRequests;

  const freshness = page.getByRole("complementary", { name: "分類" }).locator(".freshness strong").nth(1);
  const previousFreshness = await freshness.innerText();
  await attachColdRefreshMutationObserver(freshness);
  const nextSnapshot = readSnapshot();
  nextSnapshot.runId = "performance-400-v2";
  nextSnapshot.generatedAt = fixedNow + 1_000;
  nextSnapshot.dataAsOf = fixedNow + 1_000;
  writeJsonAtomically(snapshotPath, nextSnapshot);
  const coldResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/dashboard/snapshot" && response.status() === 200;
  }, { timeout: 70_000 });
  await coldResponse;
  await expect.poll(() => freshness.innerText(), { timeout: 10_000 }).not.toBe(previousFreshness);
  await page.waitForTimeout(250);
  const afterCold = await browserMetrics(page);
  expect(afterCold.coldFetchEnds.length).toBeGreaterThan(0);
  expect(afterCold.coldApplyDurations.length).toBeGreaterThan(0);
  const coldWindowStart = afterCold.coldFetchEnds.at(-1) as number;
  evidence.coldApplyMs = afterCold.coldApplyDurations.at(-1) as number;
  const coldWindowEnd = coldWindowStart + evidence.coldApplyMs;
  const coldLongTasks = longTasksInWindow(afterCold.longTasks, coldWindowStart, coldWindowEnd);
  evidence.coldLongTasksOver50Ms = coldLongTasks.length;
  evidence.coldLongTaskDurationsMs = coldLongTasks.map((entry) => entry.duration);
  evidence.coldLongTaskMaxMs = maximumOrZero(evidence.coldLongTaskDurationsMs);

  emitEvidence("browser", evidence);
  expect.soft(evidence.initialChartChunkBytes, "Dashboard initial chart chunk bytes").toBe(budgets.initialChartChunkBytes);
  expect.soft(evidence.hotLongTasksOver50Ms, "Hot ticker steady-state Long Tasks over 50ms").toBe(budgets.hotLongTasksOver50Ms);
  expect.soft(evidence.coldLongTaskMaxMs, "Cold refresh maximum Long Task ms").toBeLessThanOrEqual(budgets.coldLongTaskMaxMs);
  expect.soft(evidence.coldApplyMs, "Cold refresh apply ms").toBeLessThanOrEqual(budgets.coldApplyMs);
  expect.soft(evidence.hotApplyP95Ms, "Hot ticker apply p95 ms").toBeLessThanOrEqual(budgets.hotApplyP95Ms);
  expect.soft(evidence.rawSortWarmupMaxMs, "Raw Sort first-use maximum ms").toBeLessThanOrEqual(budgets.rawSortWarmupMaxMs);
  expect.soft(evidence.rawSortP95Ms, "Raw Sort p95 ms").toBeLessThanOrEqual(budgets.rawSortP95Ms);
  expect.soft(evidence.hiddenPollRequests, "hidden tab poll requests").toBe(budgets.hiddenPollRequests);
});

function generate400SymbolFixture() {
  const snapshot = readSnapshot();
  const originalRows = snapshot.rows.map((row) => structuredClone(row));
  if (originalRows.length !== 5) throw new Error(`basic fixture row count changed: ${originalRows.length}`);
  const addedRows = Array.from({ length: 395 }, (_, index): SnapshotRow => {
    const base = structuredClone(originalRows[index % originalRows.length]);
    const offset = (index + 1) / 1_000;
    return {
      ...base,
      symbol: `PERF${String(index + 1).padStart(4, "0")}USDT`,
      lastPrice: positiveNumber(base.lastPrice, 10) + offset,
      analysisPrice: positiveNumber(base.analysisPrice, 10) + offset,
      changePctByTf: offsetRecord(base.changePctByTf, offset),
      turnoverUsdtByTf: offsetRecord(base.turnoverUsdtByTf, index + 1),
      volumeRatioByTf: offsetRecord(base.volumeRatioByTf, offset)
    };
  });
  snapshot.runId = "performance-400-v1";
  snapshot.generatedAt = fixedNow;
  snapshot.dataAsOf = fixedNow;
  snapshot.rows = [...originalRows, ...addedRows];
  snapshot.summary = {
    ...snapshot.summary,
    serviceSource: "duckdb-service",
    counts: countCategories(snapshot.rows)
  };
  writeJsonAtomically(snapshotPath, snapshot);
  return snapshot.rows;
}

function readSnapshot() {
  return JSON.parse(readFileSync(snapshotPath, "utf-8")) as SnapshotFixture;
}

function writeServiceState() {
  writeJsonAtomically(serviceStatePath, {
    schemaVersion: 1,
    generatedAtMs: fixedNow,
    dataAsOfMs: fixedNow,
    productType: "USDT-FUTURES",
    streamSymbols: 400,
    streamChannels: 2,
    streamShards: 1,
    diagnostics: { tickerCount: 400, candle1mCount: 400, latestCandle1mTsMs: fixedNow }
  });
}

function writeDetailChartFixture(snapshotRunId: string, symbol: string) {
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
    generatedAt: fixedNow,
    dataAsOf: fixedNow,
    timeframes
  });
}

function writeTickerRuntime(sequence: number, currentFull: TickerUpdate[], deltaUpdates: TickerUpdate[]) {
  writeJsonAtomically(tickerRuntimePath, {
    schemaVersion: 1,
    sequence,
    asOf: Math.max(...currentFull.map((update) => update[2])),
    fullUpdates: currentFull,
    deltaUpdates
  });
}

function writeJsonAtomically(path: string, value: unknown) {
  mkdirSync(resolve(path, ".."), { recursive: true });
  const temporaryPath = `${path}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify(value)}\n`, "utf-8");
  renameSync(temporaryPath, path);
}

async function measureNativeVisibilityAndPolling() {
  const proxy = await startVisibilityProxy();
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
      proxy.origin
    ],
    {
      stdio: "ignore",
      env: {
        ...process.env,
        HOME: performanceRoot,
        XDG_CONFIG_HOME: resolve(performanceRoot, "native-config")
      }
    }
  );
  try {
    const devtoolsPort = await readDevtoolsPort(chrome);
    const target = await waitForPageTarget(devtoolsPort, proxy.origin, chrome);
    await waitUntil(() => proxy.tickerRequestCount() > 0, 10_000, "native Dashboard ticker did not start");
    await evaluateAndDetach(
      target.webSocketDebuggerUrl,
      `(() => {
  const report = () => fetch("/__visibility-probe", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ state: document.visibilityState, at: Date.now() }),
    keepalive: true
  });
  document.addEventListener("visibilitychange", report);
  void report();
})()`
    );
    await waitUntil(
      () => proxy.visibilityEvents.some((event) => event.state === "visible"),
      5_000,
      "native Dashboard did not report initial visible state"
    );
    await delay(250);

    execFileSync(
      "xdotool",
      ["search", "--name", "準備監視板", "windowactivate", "--sync", "key", "ctrl+t"],
      { stdio: "pipe" }
    );
    await waitUntil(
      () => proxy.visibilityEvents.some((event) => event.state === "hidden"),
      10_000,
      "native Dashboard did not report hidden after real Ctrl+T"
    );
    await delay(150);
    const hiddenBaseline = proxy.tickerRequestCount();
    await delay(2_200);
    const hiddenPollRequests = proxy.tickerRequestCount() - hiddenBaseline;

    const restoreTickerBaseline = proxy.tickerRequestCount();
    execFileSync("xdotool", ["getactivewindow", "key", "ctrl+w"], { stdio: "pipe" });
    await waitUntil(
      () => proxy.visibilityEvents.at(-1)?.state === "visible",
      10_000,
      "native Dashboard did not report visible after closing foreground tab"
    );
    await waitUntil(
      () => proxy.tickerRequestCount() > restoreTickerBaseline,
      5_000,
      "native Dashboard did not poll immediately after visible restore"
    );

    return {
      hiddenState: "hidden" as const,
      visibleStateAfterRestore: "visible" as const,
      hiddenPollRequests
    };
  } finally {
    await stopChild(chrome);
    await proxy.close();
  }
}

async function startVisibilityProxy() {
  const visibilityEvents: NativeVisibilityEvent[] = [];
  let tickerRequests = 0;
  const server = createServer((request, response) => {
    void handleVisibilityProxyRequest(request, response, visibilityEvents, () => {
      tickerRequests += 1;
    }).catch((cause) => {
      response.statusCode = 502;
      response.end(cause instanceof Error ? cause.message : "visibility proxy failure");
    });
  });
  await new Promise<void>((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", () => resolveListen());
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("visibility proxy address unavailable");
  return {
    origin: `http://127.0.0.1:${address.port}`,
    visibilityEvents,
    tickerRequestCount: () => tickerRequests,
    close: () => closeServer(server)
  };
}

async function handleVisibilityProxyRequest(
  request: IncomingMessage,
  response: import("node:http").ServerResponse,
  visibilityEvents: NativeVisibilityEvent[],
  recordTickerRequest: () => void
) {
  const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
  if (requestUrl.pathname === "/__visibility-probe") {
    const body = Buffer.concat(await readIncomingBody(request));
    const event = JSON.parse(body.toString("utf-8")) as NativeVisibilityEvent;
    if (!event || !["hidden", "visible"].includes(event.state) || !Number.isFinite(event.at)) {
      response.statusCode = 400;
      response.end("invalid visibility event");
      return;
    }
    visibilityEvents.push(event);
    response.statusCode = 204;
    response.end();
    return;
  }
  if (requestUrl.pathname === "/api/runtime/tickers") recordTickerRequest();

  const headers = new Headers();
  for (const [name, value] of Object.entries(request.headers)) {
    if (!value || ["host", "connection", "content-length", "accept-encoding"].includes(name)) continue;
    headers.set(name, Array.isArray(value) ? value.join(", ") : value);
  }
  const method = request.method ?? "GET";
  const incomingBody = method === "GET" || method === "HEAD" ? undefined : Buffer.concat(await readIncomingBody(request));
  const upstream = await fetch(`http://127.0.0.1:4174${request.url ?? "/"}`, {
    method,
    headers,
    body: incomingBody ? new Uint8Array(incomingBody) : undefined,
    redirect: "manual"
  });
  response.statusCode = upstream.status;
  upstream.headers.forEach((value, name) => {
    if (["content-encoding", "content-length", "connection"].includes(name)) return;
    response.setHeader(name, value);
  });
  response.end(Buffer.from(await upstream.arrayBuffer()));
}

async function readIncomingBody(request: IncomingMessage) {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  return chunks;
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

async function waitForPageTarget(port: number, origin: string, chrome: ChildProcess) {
  let target: { url: string; type: string; webSocketDebuggerUrl: string } | undefined;
  await waitUntil(async () => {
    if (chrome.exitCode !== null) throw new Error(`native Chrome exited with ${chrome.exitCode}`);
    const response = await fetch(`http://127.0.0.1:${port}/json/list`).catch(() => null);
    if (!response?.ok) return false;
    const targets = (await response.json()) as Array<{
      url: string;
      type: string;
      webSocketDebuggerUrl: string;
    }>;
    target = targets.find((candidate) => candidate.type === "page" && candidate.url.startsWith(origin));
    return target !== undefined;
  }, 10_000, "native Dashboard target unavailable");
  if (!target) throw new Error("native Dashboard target unavailable");
  return target;
}

async function evaluateAndDetach(webSocketUrl: string, expression: string) {
  const socket = new WebSocket(webSocketUrl);
  await new Promise<void>((resolveOpen, rejectOpen) => {
    socket.addEventListener("open", () => resolveOpen(), { once: true });
    socket.addEventListener("error", () => rejectOpen(new Error("native CDP connection failed")), {
      once: true
    });
  });
  const response = new Promise<void>((resolveResponse, rejectResponse) => {
    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(String(event.data)) as {
        id?: number;
        error?: { message?: string };
        result?: { result?: { exceptionDetails?: { text?: string } } };
      };
      if (payload.id !== 1) return;
      if (payload.error || payload.result?.result?.exceptionDetails) {
        rejectResponse(
          new Error(payload.error?.message ?? payload.result?.result?.exceptionDetails?.text ?? "native CDP evaluation failed")
        );
      } else {
        resolveResponse();
      }
    });
  });
  socket.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression } }));
  await response;
  socket.close();
  await delay(100);
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

function closeServer(server: Server) {
  return new Promise<void>((resolveClose, rejectClose) => {
    server.close((cause) => (cause ? rejectClose(cause) : resolveClose()));
  });
}

function tickerUpdates(snapshotRows: SnapshotRow[], ts: number): TickerUpdate[] {
  return snapshotRows.map((row, index) => [row.symbol, positiveNumber(row.lastPrice, 100 + index), ts]);
}

function replaceTicker(current: TickerUpdate[], update: TickerUpdate) {
  return current.map((candidate) => (candidate[0] === update[0] ? update : candidate));
}

function positiveNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : fallback;
}

function offsetRecord(source: Record<string, number> | undefined, offset: number) {
  return Object.fromEntries(Object.entries(source ?? {}).map(([key, value]) => [key, value + offset]));
}

function countCategories(snapshotRows: SnapshotRow[]) {
  return snapshotRows.reduce<Record<string, number>>((counts, row) => {
    counts[row.category] = (counts[row.category] ?? 0) + 1;
    return counts;
  }, {});
}

function maximumEmbeddedBarCount(snapshot: SnapshotFixture) {
  let maximum = 0;
  for (const row of snapshot.rows) {
    maximum = Math.max(maximum, row.sparkline?.points?.length ?? 0, row.sparkline?.bars?.length ?? 0);
    for (const bars of Object.values(row.sparkline?.timeframes ?? {})) maximum = Math.max(maximum, bars.length);
  }
  return maximum;
}

function maximumDetailBarCount() {
  let maximum = 0;
  for (const name of readdirSync(chartsDir).filter((candidate) => candidate.endsWith(".json"))) {
    const payload = JSON.parse(readFileSync(resolve(chartsDir, name), "utf-8")) as {
      timeframes?: Record<string, unknown[]>;
    };
    for (const bars of Object.values(payload.timeframes ?? {})) maximum = Math.max(maximum, bars.length);
  }
  return maximum;
}

function percentile95(values: number[]) {
  if (values.length === 0) throw new Error("p95 requires at least one sample");
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.ceil(sorted.length * 0.95) - 1];
}

function productionChartChunkPath() {
  const manifest = JSON.parse(readFileSync(clientManifestPath, "utf-8")) as Record<
    string,
    { file?: unknown; src?: unknown }
  >;
  const chartEntry = Object.values(manifest).find(
    (entry) => typeof entry.src === "string" && entry.src.includes("lightweight-charts")
  );
  if (!chartEntry || typeof chartEntry.file !== "string") throw new Error("production chart chunk missing");
  return `/${chartEntry.file}`;
}

async function installBrowserInstrumentation(page: Page) {
  await page.addInitScript(() => {
    const metrics: BrowserMetrics = {
      longTasks: [],
      hotFetchEnds: [],
      hotApplyDurations: [],
      hotConsumedResponses: 0,
      coldFetchEnds: [],
      coldApplyDurations: [],
      coldConsumedResponses: 0
    };
    (window as Window & typeof globalThis & { __watchdeckPerformance: BrowserMetrics }).__watchdeckPerformance = metrics;
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) metrics.longTasks.push({ startTime: entry.startTime, duration: entry.duration });
    });
    observer.observe({ type: "longtask", buffered: true });
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      const requestUrl = new URL(
        typeof args[0] === "string" || args[0] instanceof URL ? String(args[0]) : args[0].url,
        window.location.href
      );
      if (requestUrl.pathname === "/api/runtime/tickers" && response.status === 200) {
        metrics.hotFetchEnds.push(performance.now());
      }
      if (requestUrl.pathname === "/api/dashboard/snapshot" && response.status === 200) {
        metrics.coldFetchEnds.push(performance.now());
      }
      return response;
    };
  });
}

async function attachPriceMutationObserver(page: Page, priceText: ReturnType<Page["locator"]>) {
  await priceText.evaluate((element) => {
    const metrics = (window as Window & typeof globalThis & { __watchdeckPerformance: BrowserMetrics }).__watchdeckPerformance;
    metrics.hotConsumedResponses = metrics.hotFetchEnds.length;
    const observer = new MutationObserver(() => {
      const responseIndex = metrics.hotConsumedResponses;
      if (metrics.hotFetchEnds.length <= responseIndex) return;
      metrics.hotApplyDurations.push(performance.now() - metrics.hotFetchEnds[responseIndex]);
      metrics.hotConsumedResponses += 1;
    });
    observer.observe(element, { characterData: true, childList: true, subtree: true });
  });
}

async function attachColdRefreshMutationObserver(
  freshnessText: ReturnType<Page["locator"]>
) {
  await freshnessText.evaluate((element) => {
    const metrics = (window as Window & typeof globalThis & { __watchdeckPerformance: BrowserMetrics }).__watchdeckPerformance;
    metrics.coldConsumedResponses = metrics.coldFetchEnds.length;
    const observer = new MutationObserver(() => {
      const responseIndex = metrics.coldConsumedResponses;
      if (metrics.coldFetchEnds.length <= responseIndex) return;
      metrics.coldApplyDurations.push(performance.now() - metrics.coldFetchEnds[responseIndex]);
      metrics.coldConsumedResponses += 1;
      observer.disconnect();
    });
    observer.observe(element, { characterData: true, childList: true, subtree: true });
  });
}

async function browserMetrics(page: Page) {
  return page.evaluate(() =>
    structuredClone(
      (window as Window & typeof globalThis & { __watchdeckPerformance: BrowserMetrics }).__watchdeckPerformance
    )
  );
}

async function measureRawSort(page: Page, samples: number) {
  return page.evaluate(async (sampleCount) => {
    const group = document.querySelector<HTMLElement>('[role="group"][aria-label="時間軸ショートカット"]');
    const buttons = group ? Array.from(group.querySelectorAll<HTMLButtonElement>("button")) : [];
    const timeframeButton = (timeframe: string) =>
      buttons.find((button) => button.textContent?.trim() === timeframe);
    if (!timeframeButton("1h") || !timeframeButton("15m")) {
      throw new Error("Common timeframe controls are missing");
    }
    const measureToggle = async (timeframe: "1h" | "15m") => {
      await new Promise<void>((resolveFrame) => requestAnimationFrame(() => resolveFrame()));
      const button = timeframeButton(timeframe);
      if (!button) throw new Error(`Missing timeframe button: ${timeframe}`);
      const start = performance.now();
      return new Promise<number>((resolveDuration, rejectDuration) => {
        const timeout = window.setTimeout(() => {
          observer.disconnect();
          rejectDuration(new Error(`Raw Sort DOM update timed out: ${timeframe}`));
        }, 1_000);
        const observer = new MutationObserver(() => {
          window.clearTimeout(timeout);
          observer.disconnect();
          resolveDuration(performance.now() - start);
        });
        observer.observe(button, { attributes: true, attributeFilter: ["aria-pressed"] });
        button.click();
      });
    };
    const warmupDurationsMs = [await measureToggle("1h"), await measureToggle("15m")];
    const sampleDurationsMs: number[] = [];
    for (let index = 0; index < sampleCount; index += 1) {
      sampleDurationsMs.push(await measureToggle(index % 2 === 0 ? "1h" : "15m"));
    }
    return { warmupDurationsMs, sampleDurationsMs };
  }, samples);
}

function longTasksInWindow(entries: BrowserMetrics["longTasks"], start: number, end: number) {
  return entries.filter((entry) => entry.startTime >= start && entry.startTime <= end && entry.duration > 50);
}

function maximumOrZero(values: number[]) {
  return values.length === 0 ? 0 : Math.max(...values);
}

function emitEvidence(section: string, evidence: PerformanceEvidence) {
  console.log(`PERFORMANCE_EVIDENCE ${section} ${JSON.stringify(evidence)}`);
}
