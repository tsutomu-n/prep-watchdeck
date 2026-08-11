import { expect, test, type Page, type Request } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const scannerCoreDir = resolve(process.cwd(), "../scanner-core");
const e2ePaths = resolveWebTestStatePaths("e2e");
const e2eSnapshotPath = e2ePaths.snapshotPath;
const e2eTickerRuntimePath = e2ePaths.tickerRuntimePath;
const clientManifestPath = resolve(process.cwd(), ".svelte-kit/output/client/.vite/manifest.json");

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
  summary: { counts: Record<string, number>; [key: string]: unknown };
  rows: SnapshotRow[];
  [key: string]: unknown;
};

type TickerUpdate = [symbol: string, lastPrice: number, ts: number];

test.describe.configure({ mode: "serial" });

function generateBasicSnapshot() {
  execFileSync(
    "uv",
    [
      "run",
      "watchdeck",
      "scan",
      "--source",
      "fixture",
      "--fixture-set",
      "basic",
      "--template",
      "balanced"
    ],
    {
      cwd: scannerCoreDir,
      env: {
        ...process.env,
        PREP_WATCHDECK_STATE_DIR: e2ePaths.runtimeRoot
      },
      stdio: "pipe"
    }
  );
}

function generate400SymbolSnapshot() {
  generateBasicSnapshot();
  const snapshot = JSON.parse(readFileSync(e2eSnapshotPath, "utf-8")) as SnapshotFixture;
  const base = snapshot.rows.find((row) => row.symbol === "SLEEPUSDT");
  if (!base) throw new Error("basic fixture SLEEPUSDT row is missing");

  const addedRows = Array.from({ length: 395 }, (_, index): SnapshotRow => ({
    ...structuredClone(base),
    symbol: `E2E${String(index + 1).padStart(4, "0")}USDT`,
    lastPrice: 10 + index / 100,
    analysisPrice: 10 + index / 100,
    changePctByTf: {},
    turnoverUsdtByTf: {},
    volumeRatioByTf: {}
  }));
  snapshot.rows = [...snapshot.rows, ...addedRows];
  snapshot.summary.counts.LOW_PRIORITY = (snapshot.summary.counts.LOW_PRIORITY ?? 0) + addedRows.length;
  writeJsonAtomically(e2eSnapshotPath, snapshot);
  return snapshot.rows;
}

function addVpiLitePlusSnapshotPayload() {
  const snapshot = JSON.parse(readFileSync(e2eSnapshotPath, "utf-8")) as SnapshotFixture & {
    generatedAt: number;
  };
  const item = {
    symbol: "THINUSDT",
    state: "EARLY_ACTIVITY",
    score: 48.5,
    reasonCodes: ["ABS_RETURN_UP", "TURNOVER_UP"],
    riskTagCodes: ["THIN_TURNOVER"],
    fundingState: "NORMAL",
    openInterestState: "AVAILABLE",
    dataQuality: "OK",
    dataAsOf: snapshot.generatedAt - 60_000
  };
  snapshot.summary.vpiLitePlus = {
    schemaVersion: 1,
    mode: "lite_plus_v0",
    generatedAt: snapshot.generatedAt,
    benchmarks: [
      { ...item, symbol: "BTCUSDT", state: "CALM", score: 12.5 },
      { ...item, symbol: "ETHUSDT", state: "DATA_STALE", score: 0, dataQuality: "STALE" }
    ],
    targets: [item]
  };
  const row = snapshot.rows.find((candidate) => candidate.symbol === item.symbol);
  if (!row) throw new Error("THINUSDT fixture row not found");
  const display =
    row.display && typeof row.display === "object" && !Array.isArray(row.display)
      ? (row.display as Record<string, unknown>)
      : {};
  row.display = { ...display, vpiLitePlus: item };
  writeJsonAtomically(e2eSnapshotPath, snapshot);
  return snapshot.rows;
}

function addMarketComparisonSnapshotPayload() {
  const snapshot = JSON.parse(readFileSync(e2eSnapshotPath, "utf-8")) as SnapshotFixture & {
    generatedAt: number;
  };
  snapshot.summary.marketComparison = {
    schemaVersion: 1,
    mode: "mark_price_pilot_v1",
    generatedAt: snapshot.generatedAt,
    refreshIntervalSeconds: 300,
    symbols: [
      marketComparisonItem("BTCUSDT", 100, snapshot.generatedAt),
      marketComparisonItem("ETHUSDT", 200, snapshot.generatedAt),
      marketComparisonItem("SOLUSDT", 300, snapshot.generatedAt)
    ]
  };
  writeJsonAtomically(e2eSnapshotPath, snapshot);
  return snapshot.rows;
}

function marketComparisonItem(symbol: string, medianPrice: number, observedAt: number) {
  const coin = symbol.replace(/USDT$/, "");
  return {
    symbol,
    status: "ready",
    coverage: { valid: 3, required: 3 },
    medianMarkPrice: medianPrice,
    spreadPct: 1.98,
    sources: [
      marketComparisonSource("bitget", symbol, "USDT", medianPrice - 1, observedAt),
      marketComparisonSource("hyperliquid", coin, "USD", medianPrice, observedAt),
      marketComparisonSource("bybit", symbol, "USDT", medianPrice + 1, observedAt)
    ]
  };
}

function marketComparisonSource(
  source: "bitget" | "hyperliquid" | "bybit",
  sourceSymbol: string,
  quote: string,
  markPrice: number,
  observedAt: number
) {
  return {
    source,
    status: "ok",
    sourceSymbol,
    quote,
    markPrice,
    observedAt,
    sourceAt: source === "hyperliquid" ? null : observedAt,
    error: null
  };
}

function removeEmbeddedChartData(symbol: string) {
  const snapshot = JSON.parse(readFileSync(e2eSnapshotPath, "utf-8")) as SnapshotFixture;
  const row = snapshot.rows.find((candidate) => candidate.symbol === symbol);
  if (!row) throw new Error(`E2E snapshot row is missing: ${symbol}`);
  const sparkline =
    row.sparkline && typeof row.sparkline === "object" && !Array.isArray(row.sparkline)
      ? { ...(row.sparkline as Record<string, unknown>) }
      : {};
  sparkline.points = [];
  delete sparkline.bars;
  delete sparkline.timeframes;
  row.sparkline = sparkline;
  writeJsonAtomically(e2eSnapshotPath, snapshot);
}

function writeTickerRuntime(sequence: number, fullUpdates: TickerUpdate[], deltaUpdates: TickerUpdate[]) {
  writeJsonAtomically(e2eTickerRuntimePath, {
    schemaVersion: 1,
    sequence,
    asOf: Math.max(...fullUpdates.map((update) => update[2])),
    fullUpdates,
    deltaUpdates
  });
}

function writeJsonAtomically(path: string, value: unknown) {
  mkdirSync(resolve(path, ".."), { recursive: true });
  const tempPath = `${path}.${process.pid}.tmp`;
  writeFileSync(tempPath, `${JSON.stringify(value)}\n`, "utf-8");
  renameSync(tempPath, path);
}

function tickerUpdates(rows: SnapshotRow[], ts: number): TickerUpdate[] {
  return rows.map((row, index) => [
    row.symbol,
    typeof row.lastPrice === "number" && row.lastPrice > 0 ? row.lastPrice : 100 + index,
    ts
  ]);
}

function recordChartRequests(page: Page) {
  const requests: Request[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (/^\/api\/symbols\/[^/]+\/chart$/.test(url.pathname)) requests.push(request);
  });
  return requests;
}

function recordScriptPaths(page: Page) {
  const paths: string[] = [];
  page.on("request", (request) => {
    if (request.resourceType() === "script") paths.push(new URL(request.url()).pathname);
  });
  return paths;
}

function chartChunkPath() {
  const manifest = JSON.parse(readFileSync(clientManifestPath, "utf-8")) as Record<
    string,
    { file?: unknown; src?: unknown }
  >;
  const chartEntry = Object.values(manifest).find(
    (entry) => typeof entry.src === "string" && entry.src.includes("lightweight-charts")
  );
  if (!chartEntry || typeof chartEntry.file !== "string") {
    throw new Error("lightweight-charts chunk is missing from the production manifest");
  }
  return `/${chartEntry.file}`;
}

function currentSnapshotRunId() {
  const snapshot = JSON.parse(readFileSync(e2eSnapshotPath, "utf-8")) as { runId?: unknown };
  if (typeof snapshot.runId !== "string" || snapshot.runId.length === 0) {
    throw new Error("E2E snapshot runId is missing");
  }
  return snapshot.runId;
}

async function waitForClientRuntime(page: Page) {
  const tickerRequest = page.waitForRequest((request) =>
    new URL(request.url()).pathname.endsWith("/api/runtime/tickers")
  );
  await page.goto("/");
  await tickerRequest;
  await expect(page.getByRole("heading", { name: "ローカル市場監視" })).toBeVisible();
}

test("Dashboard chart loads only on first expansion and keeps the same instance", async ({ page }) => {
  generateBasicSnapshot();
  const chartRequests = recordChartRequests(page);
  const scriptPaths = recordScriptPaths(page);

  await waitForClientRuntime(page);
  const chartChunk = chartChunkPath();
  const contextGroup = page.locator('details[data-detail-group="context"]');

  await expect(contextGroup).not.toHaveAttribute("open", "");
  await expect(contextGroup.locator(".chart-surface")).toHaveCount(0);
  expect(chartRequests).toHaveLength(0);
  expect(scriptPaths.filter((path) => path === chartChunk)).toHaveLength(0);

  await contextGroup.locator("summary").click();
  const chartSurface = contextGroup.locator(".chart-surface");
  await expect(chartSurface).toBeVisible();
  await expect.poll(() => chartRequests.length).toBe(1);
  await expect.poll(() => scriptPaths.filter((path) => path === chartChunk).length).toBe(1);

  const chartUrl = new URL(chartRequests[0].url());
  expect(chartUrl.searchParams.get("runId")).toBe(currentSnapshotRunId());
  const initialSurface = await chartSurface.elementHandle();
  expect(initialSurface).not.toBeNull();

  await contextGroup.locator("summary").click();
  await expect(chartSurface).toBeHidden();
  await contextGroup.locator("summary").click();
  await expect(chartSurface).toBeVisible();

  const reopenedSurface = await chartSurface.elementHandle();
  expect(reopenedSurface).not.toBeNull();
  expect(
    await page.evaluate(
      ([initial, reopened]) => initial === reopened,
      [initialSurface, reopenedSurface]
    )
  ).toBe(true);
  expect(chartRequests).toHaveLength(1);
  expect(scriptPaths.filter((path) => path === chartChunk)).toHaveLength(1);
});

test("Dashboard chart does not initialize after unmount while its module is pending", async ({
  page
}) => {
  generateBasicSnapshot();
  const chartRequests = recordChartRequests(page);
  const scriptPaths = recordScriptPaths(page);

  await page.addInitScript(() => {
    const lifecycle = {
      loaderStarted: 0,
      loaderResolved: 0,
      createCalls: 0,
      created: 0,
      removed: 0,
      observerCreated: 0,
      observerDisconnected: 0
    };
    let releaseLoader = () => {};
    const loaderGate = new Promise<void>((resolveGate) => {
      releaseLoader = resolveGate;
    });
    const instrumentedWindow = window as Window &
      typeof globalThis & {
        __watchdeckChartLifecycle?: typeof lifecycle;
        __watchdeckChartLoaderGate?: { release: () => void };
        __watchdeckInstrumentation?: {
          chartCreated: () => void;
          chartRemoved: () => void;
          chartResizeObserverCreated: () => void;
          chartResizeObserverDisconnected: () => void;
          loadChartModule: (
            loadDefault: () => Promise<Record<string, unknown>>
          ) => Promise<Record<string, unknown>>;
        };
      };
    instrumentedWindow.__watchdeckChartLifecycle = lifecycle;
    instrumentedWindow.__watchdeckChartLoaderGate = { release: () => releaseLoader() };
    instrumentedWindow.__watchdeckInstrumentation = {
      chartCreated() {
        lifecycle.created += 1;
      },
      chartRemoved() {
        lifecycle.removed += 1;
      },
      chartResizeObserverCreated() {
        lifecycle.observerCreated += 1;
      },
      chartResizeObserverDisconnected() {
        lifecycle.observerDisconnected += 1;
      },
      async loadChartModule(loadDefault) {
        lifecycle.loaderStarted += 1;
        await loaderGate;
        const chartModule = await loadDefault();
        lifecycle.loaderResolved += 1;
        return {
          ...chartModule,
          createChart(...args: unknown[]) {
            lifecycle.createCalls += 1;
            return (chartModule.createChart as (...createArgs: unknown[]) => unknown)(...args);
          }
        };
      }
    };
  });

  await waitForClientRuntime(page);
  const chartChunk = chartChunkPath();
  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await watchlist.locator('[data-row-select][data-symbol="THINUSDT"]').click();
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();

  let contextGroup = detail.locator('details[data-detail-group="context"]');
  await contextGroup.locator("summary").click();
  await expect(contextGroup.locator(".chart-surface")).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as Window &
              typeof globalThis & {
                __watchdeckChartLifecycle?: { loaderStarted: number };
              }
          ).__watchdeckChartLifecycle?.loaderStarted ?? 0
      )
    )
    .toBe(1);
  expect(scriptPaths.filter((path) => path === chartChunk)).toHaveLength(0);

  const viewGroup = page.getByRole("group", { name: "ビュー" });
  await viewGroup.getByRole("button", { name: "低品質除外" }).click();
  await expect(detail.getByText("選択銘柄を保持中")).toBeVisible();
  await expect(detail.locator(".chart-surface")).toHaveCount(0);

  await page.evaluate(() => {
    (
      window as Window &
        typeof globalThis & { __watchdeckChartLoaderGate?: { release: () => void } }
    ).__watchdeckChartLoaderGate?.release();
  });
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as Window &
              typeof globalThis & {
                __watchdeckChartLifecycle?: { loaderResolved: number };
              }
          ).__watchdeckChartLifecycle?.loaderResolved ?? 0
      )
    )
    .toBe(1);
  await page.evaluate(
    () =>
      new Promise<void>((resolveFrame) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolveFrame()))
      )
  );
  expect(
    await page.evaluate(
      () =>
        (
          window as Window &
            typeof globalThis & {
              __watchdeckChartLifecycle?: {
                createCalls: number;
                created: number;
                removed: number;
                observerCreated: number;
                observerDisconnected: number;
              };
            }
        ).__watchdeckChartLifecycle
    )
  ).toMatchObject({
    createCalls: 0,
    created: 0,
    removed: 0,
    observerCreated: 0,
    observerDisconnected: 0
  });

  await viewGroup.getByRole("button", { name: "標準" }).click();
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();
  contextGroup = detail.locator('details[data-detail-group="context"]');
  await contextGroup.locator("summary").click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as Window &
              typeof globalThis & {
                __watchdeckChartLifecycle?: { created: number };
              }
          ).__watchdeckChartLifecycle?.created ?? 0
      )
    )
    .toBe(1);
  await viewGroup.getByRole("button", { name: "低品質除外" }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as Window &
              typeof globalThis & {
                __watchdeckChartLifecycle?: { removed: number };
              }
          ).__watchdeckChartLifecycle?.removed ?? 0
      )
    )
    .toBe(1);

  expect(
    await page.evaluate(
      () =>
        (
          window as Window &
            typeof globalThis & {
              __watchdeckChartLifecycle?: {
                loaderStarted: number;
                loaderResolved: number;
                createCalls: number;
                created: number;
                removed: number;
                observerCreated: number;
                observerDisconnected: number;
              };
            }
        ).__watchdeckChartLifecycle
    )
  ).toEqual({
    loaderStarted: 2,
    loaderResolved: 2,
    createCalls: 1,
    created: 1,
    removed: 1,
    observerCreated: 1,
    observerDisconnected: 1
  });
  expect(scriptPaths.filter((path) => path === chartChunk)).toHaveLength(1);
  expect(chartRequests.length).toBeGreaterThanOrEqual(2);
  expect(
    chartRequests.every(
      (request) => new URL(request.url()).searchParams.get("runId") === currentSnapshotRunId()
    )
  ).toBe(true);
});

test("Symbol page requests and displays its chart immediately", async ({ page }) => {
  generateBasicSnapshot();
  const chartRequests = recordChartRequests(page);
  const scriptPaths = recordScriptPaths(page);

  await page.goto("/symbols/ALTUSDT?tf=15m");
  const chartChunk = chartChunkPath();
  const primaryChart = page.getByRole("region", { name: "主チャート" });

  await expect(primaryChart.locator(".chart-surface")).toBeVisible();
  await expect.poll(() => chartRequests.length).toBe(1);
  await expect.poll(() => scriptPaths.filter((path) => path === chartChunk).length).toBe(1);
  expect(new URL(chartRequests[0].url()).searchParams.get("runId")).toBe(currentSnapshotRunId());
});

test("Symbol chart initializes once before API-only bars arrive and exposes an OHLCV summary", async ({
  page
}) => {
  generateBasicSnapshot();
  removeEmbeddedChartData("ALTUSDT");
  const runId = currentSnapshotRunId();
  const chartRequests = recordChartRequests(page);
  const scriptPaths = recordScriptPaths(page);
  let releaseChartResponse = () => {};
  const chartResponseGate = new Promise<void>((resolveGate) => {
    releaseChartResponse = resolveGate;
  });

  await page.addInitScript(() => {
    const lifecycle = { created: 0, removed: 0 };
    const instrumentedWindow = window as Window &
      typeof globalThis & {
        __watchdeckChartLifecycle?: typeof lifecycle;
        __watchdeckInstrumentation?: {
          chartCreated: () => void;
          chartRemoved: () => void;
        };
      };
    instrumentedWindow.__watchdeckChartLifecycle = lifecycle;
    instrumentedWindow.__watchdeckInstrumentation = {
      chartCreated() {
        lifecycle.created += 1;
      },
      chartRemoved() {
        lifecycle.removed += 1;
      }
    };
  });
  await page.route("**/api/symbols/ALTUSDT/chart?*", async (route) => {
    await chartResponseGate;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        schemaVersion: 2,
        snapshotRunId: runId,
        symbol: "ALTUSDT",
        generatedAt: 1_700_000_900_000,
        dataAsOf: 1_700_000_900_000,
        timeframes: {
          "15m": [
            {
              ts: 1_700_000_000_000,
              open: 10,
              high: 12,
              low: 9,
              close: 11,
              quoteVolume: 800
            },
            {
              ts: 1_700_000_900_000,
              open: 11,
              high: 13,
              low: 10.5,
              close: 12.5,
              quoteVolume: 1_000
            }
          ]
        }
      })
    });
  });

  await page.goto("/symbols/ALTUSDT?tf=15m");
  const chartChunk = chartChunkPath();
  const chart = page.getByRole("region", { name: "ALT チャート" });
  await expect(chart.locator(".chart-surface")).toBeVisible();
  await expect(chart.getByText("ローソク足データなし", { exact: true })).toBeVisible();
  await expect(chart).toHaveAccessibleDescription(
    "ALT 15m足。表示できる価格データはありません。"
  );
  await expect.poll(() => chartRequests.length).toBe(1);
  await expect.poll(() => scriptPaths.filter((path) => path === chartChunk).length).toBe(1);
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (
            window as Window &
              typeof globalThis & { __watchdeckChartLifecycle?: { created: number } }
          ).__watchdeckChartLifecycle?.created ?? 0
      )
    )
    .toBe(1);

  releaseChartResponse();

  await expect(chart.getByText("ローソク足データなし", { exact: true })).toHaveCount(0);
  await expect(chart.locator(".chart-surface canvas").first()).toBeVisible();
  await expect(chart).toHaveAccessibleDescription(
    "ALT 15m足。ローソク足2本。期間 2023-11-14 22:13:20 UTC から 2023-11-14 22:28:20 UTC。最新足は始値 11、高値 13、安値 10.5、終値 12.5、出来高 1,000。"
  );
  expect(chartRequests).toHaveLength(1);
  expect(scriptPaths.filter((path) => path === chartChunk)).toHaveLength(1);
  expect(new URL(chartRequests[0].url()).searchParams.get("runId")).toBe(runId);
  expect(
    await page.evaluate(
      () =>
        (
          window as Window &
            typeof globalThis & { __watchdeckChartLifecycle?: { created: number } }
        ).__watchdeckChartLifecycle?.created ?? 0
    )
  ).toBe(1);
});

test("a Hot delta updates only one price DOM without changing 400-row analysis state", async ({ page }) => {
  const rows = generate400SymbolSnapshot();
  const initialTs = Date.now() + 60_000;
  const initialUpdates = tickerUpdates(rows, initialTs);
  writeTickerRuntime(1, initialUpdates, []);

  await page.goto("/");
  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  const contextGroup = detail.locator('details[data-detail-group="context"]');
  await expect(watchlist.getByText("表示 400 / 全 400")).toBeVisible();
  await expect(watchlist.getByText("HOT LIVE")).toBeVisible();

  const noteReason = contextGroup.getByLabel("理由", { exact: true });
  await contextGroup.locator("summary").click();
  await noteReason.fill("400銘柄Hot更新中もTHINに固定");
  await page.getByRole("group", { name: "ビュー" }).getByRole("button", { name: "低品質除外" }).click();

  const qualityFilter = page
    .getByRole("group", { name: "ビュー" })
    .getByRole("button", { name: "低品質除外" });
  await expect(qualityFilter).toHaveAttribute("aria-pressed", "true");
  await expect(watchlist.getByText("表示 399 / 全 400")).toBeVisible();
  await expect(detail.getByText("選択銘柄を保持中")).toBeVisible();
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();

  const rowsLocator = watchlist.locator("[data-market-row][data-symbol]");
  const rowOrderBefore = await rowsLocator.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-symbol"))
  );
  expect(rowOrderBefore).toHaveLength(399);
  const ranking = page.getByRole("region", { name: "15m ランキング" });
  const rankingBefore = await ranking.innerText();

  const altRow = watchlist.locator('[data-market-row][data-symbol="ALTUSDT"]');
  const untouchedRow = watchlist.locator('[data-market-row][data-symbol="NEWALTUSDT"]');
  const altPrice = altRow.locator(".current-price");
  const untouchedPrice = untouchedRow.locator(".current-price");
  await expect(altPrice).toHaveAttribute("data-price-source", "hot");
  await expect(untouchedPrice).toHaveAttribute("data-price-source", "hot");
  const untouchedTextBefore = await untouchedPrice.innerText();
  const untouchedPriceNode = await untouchedPrice.elementHandle();
  expect(untouchedPriceNode).not.toBeNull();

  await page.evaluate(() => {
    type MutationRecordView = { symbol: string | null; inPrice: boolean };
    type TrackerWindow = Window &
      typeof globalThis & {
        __watchdeckHotMutations?: {
          records: MutationRecordView[];
          observer: MutationObserver;
        };
      };
    const records: MutationRecordView[] = [];
    const root = document.querySelector('[aria-label="精密監視リスト"] .rows');
    if (!root) throw new Error("watchlist rows root is missing");
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        const element =
          mutation.target instanceof Element ? mutation.target : mutation.target.parentElement;
        const row = element?.closest<HTMLElement>("[data-market-row]") ?? null;
        records.push({
          symbol: row?.dataset.symbol ?? null,
          inPrice: element?.closest(".current-price") !== null
        });
      }
    });
    observer.observe(root, { attributes: true, characterData: true, childList: true, subtree: true });
    (window as TrackerWindow).__watchdeckHotMutations = { records, observer };
  });

  const changedPrice = 98_765.4321;
  const changedTs = initialTs + 1;
  const changedUpdate: TickerUpdate = ["ALTUSDT", changedPrice, changedTs];
  const nextFull = initialUpdates.map((update) =>
    update[0] === "ALTUSDT" ? changedUpdate : update
  );
  writeTickerRuntime(2, nextFull, [changedUpdate]);

  await expect(altPrice).toContainText("98,765.43");
  await expect(untouchedPrice).toHaveText(untouchedTextBefore);
  const rowOrderAfter = await rowsLocator.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-symbol"))
  );
  expect(rowOrderAfter).toEqual(rowOrderBefore);
  expect(await ranking.innerText()).toBe(rankingBefore);
  await expect(qualityFilter).toHaveAttribute("aria-pressed", "true");
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();

  const mutationRecords = await page.evaluate(() => {
    type TrackerWindow = Window &
      typeof globalThis & {
        __watchdeckHotMutations?: {
          records: Array<{ symbol: string | null; inPrice: boolean }>;
          observer: MutationObserver;
        };
      };
    const tracker = (window as TrackerWindow).__watchdeckHotMutations;
    if (!tracker) throw new Error("Hot mutation tracker is missing");
    tracker.observer.disconnect();
    return tracker.records;
  });
  expect(mutationRecords.length).toBeGreaterThan(0);
  expect(mutationRecords.every((record) => record.inPrice)).toBe(true);
  expect(mutationRecords.every((record) => record.symbol === "ALTUSDT")).toBe(true);

  const untouchedPriceAfter = await untouchedPrice.elementHandle();
  expect(untouchedPriceAfter).not.toBeNull();
  expect(
    await page.evaluate(
      ([before, after]) => before === after,
      [untouchedPriceNode, untouchedPriceAfter]
    )
  ).toBe(true);

  await page.getByRole("group", { name: "ビュー" }).getByRole("button", { name: "標準" }).click();
  await contextGroup.locator("summary").click();
  await expect(noteReason).toHaveValue("400銘柄Hot更新中もTHINに固定");
});

test("a Hot ticker delta does not recompute the Cold VPI-Lite+ display", async ({ page }) => {
  generateBasicSnapshot();
  const rows = addVpiLitePlusSnapshotPayload();
  const initialTs = Date.now() + 60_000;
  const initialUpdates = tickerUpdates(rows, initialTs);
  writeTickerRuntime(1, initialUpdates, []);

  await waitForClientRuntime(page);
  const panel = page.getByRole("region", { name: "市場活動（VPI-Lite+）" });
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  const selectedVpi = detail.getByRole("region", { name: "選択銘柄 市場活動詳細" });
  await expect(panel).toBeVisible();
  await expect(selectedVpi).toBeVisible();
  const panelBefore = await panel.innerText();
  const selectedVpiBefore = await selectedVpi.innerText();

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const altPrice = watchlist
    .locator('[data-market-row][data-symbol="ALTUSDT"]')
    .locator(".current-price");
  const changedUpdate: TickerUpdate = ["ALTUSDT", 98_765.4321, initialTs + 1];
  const nextFull = initialUpdates.map((update) =>
    update[0] === "ALTUSDT" ? changedUpdate : update
  );
  writeTickerRuntime(2, nextFull, [changedUpdate]);

  await expect(altPrice).toContainText("98,765.43");
  expect(await panel.innerText()).toBe(panelBefore);
  expect(await selectedVpi.innerText()).toBe(selectedVpiBefore);
});

test("three-market comparison remains visible without matching scanner rows", async ({ page }) => {
  generateBasicSnapshot();
  const rows = addMarketComparisonSnapshotPayload();
  writeTickerRuntime(1, tickerUpdates(rows, Date.now() + 60_000), []);

  await waitForClientRuntime(page);
  const comparison = page.getByRole("region", { name: "3市場価格比較" });
  await expect(comparison).toBeVisible();
  await expect(comparison).toContainText("BTC");
  await expect(comparison).toContainText("ETH");
  await expect(comparison).toContainText("SOL");
  await expect(comparison).toContainText("3 / 3");
  await expect(comparison).toContainText("Bitget");
  await expect(comparison).toContainText("Hyperliquid");
  await expect(comparison).toContainText("Bybit");
  await expect(comparison).toContainText("USD / USDT建て");
});
