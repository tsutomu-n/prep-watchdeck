import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import type { MarketChartArtifact, Timeframe } from "../../src/lib/generated/market-chart";
import type { SelectedMarketArtifact } from "../../src/lib/generated/selected-market";
import type { MarketServiceStateArtifact } from "../../src/lib/generated/service-state";
import type {
  UniverseInstrumentArtifact,
  UniverseSnapshotArtifact
} from "../../src/lib/generated/universe-snapshot";
import {
  REFERENCE_TIME_STORAGE_KEY,
  dailyBaselineAt,
  type DailyPriceChange
} from "../../src/lib/market/price-change";

const runtimeRoot = resolve(process.cwd(), "../../var/tmp/e2e/runtime");
const artifactRoot = resolve(runtimeRoot, "artifacts");
const selectionPath = resolve(runtimeRoot, "control", "selection.json");
const pageErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
  const now = new Date();
  await rm(selectionPath, { force: true });
  await rm(`${selectionPath}.lock`, { force: true });
  await publishArtifacts(now);
  await page.route("**/api/chart-history?*", (route) => route.fulfill({
    json: chartHistoryFixture(new URL(route.request().url()), now)
  }));
  await page.route("**/api/price-change?*", async (route) => route.fulfill({
    json: priceChangeFixture(new URL(route.request().url()), await browserNow(page))
  }));
});

test.afterEach(async ({ page }) => {
  await rm(runtimeRoot, { recursive: true, force: true });
  expect(pageErrors.get(page) ?? [], "ブラウザの未処理例外").toEqual([]);
});

test("Universe Explorerの主要flowを操作できる", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Perp Universe Explorer" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Instrument Universe" })).toBeVisible();
  await expect(page.getByLabel("運用上の注意")).toBeVisible();
  await expect(page.getByLabel("データ品質理由")).toBeVisible();

  const search = page.getByLabel("検索", { exact: true });
  await search.fill("ETH");
  await expect(page.getByRole("button", { name: "ETH bitgetを詳細表示" })).toBeVisible();
  await expect(page.getByRole("button", { name: "BTC bitgetを詳細表示" })).toHaveCount(0);
  await search.clear();

  await page.getByRole("button", { name: "BTC hyperliquidを詳細表示" }).click();
  await expect(page.getByText("詳細データを要求しました", { exact: true })).toBeVisible();
  await expect
    .poll(async () => (await readSelectionCommand())?.venueInstrumentId ?? null)
    .toBe("hyperliquid:BTC");

  const command = await readSelectionCommand();
  expect(command).toMatchObject({
    groupId: "crypto:BTC:linear-perp",
    venueInstrumentId: "hyperliquid:BTC"
  });
  await expect(
    page.getByRole("region", { name: "選択groupの板・約定" }).getByText(/artifactを待っています/)
  ).toBeVisible();

  await rm(resolve(artifactRoot, "service-state.json"), { force: true });
  await expect(page.getByText("更新停止", { exact: true })).toBeVisible({ timeout: 8_000 });
  await expect(page.getByRole("heading", { name: "Instrument Universe" })).toBeVisible();

  const horizontalOverflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
});

test("約定騰落率の基準を分単位で変更して再読み込み後も保持する", async ({ page }, testInfo) => {
  await page.goto("/");
  const setting = page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true });
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  const row = page.getByRole("row").filter({
    has: page.getByRole("button", { name: "BTC bitgetを詳細表示", exact: true })
  });
  await expect(setting).toHaveValue("00:00");
  await expect(change).toContainText("JST 00:00基準");
  await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
  await expect(change.getByText("103", { exact: true })).toBeVisible();
  await expect(change.getByText("100", { exact: true })).toBeVisible();
  await expect(row.getByRole("cell", { name: /\+3\.00%/ })).toBeVisible();
  await expect(row.getByRole("cell", { name: /65,000/ })).toBeVisible();

  const changed = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/price-change"
      && url.searchParams.get("instrument") === "bitget:BTCUSDT"
      && url.searchParams.get("referenceTime") === "09:07";
  });
  await setting.fill("09:07");
  await (await changed).finished();
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  await expect(row.getByRole("cell", { name: /-6\.36%/ })).toBeVisible();
  expect(await page.evaluate((key) => localStorage.getItem(key), REFERENCE_TIME_STORAGE_KEY))
    .toBe("09:07");

  await page.reload();
  await expect(setting).toHaveValue("09:07");
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  const horizontalOverflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
  await testInfo.attach("daily-change-layout", {
    body: JSON.stringify({ viewport: page.viewportSize(), horizontalOverflow }),
    contentType: "application/json"
  });
  await page.screenshot({ path: testInfo.outputPath("daily-change-page.png"), fullPage: true });
  await change.screenshot({ path: testInfo.outputPath("daily-change-detail.png") });
});

test("約定騰落率の古い基準の遅延応答で変更後の値を上書きしない", async ({ page }) => {
  let receiveDelayedRoute: (route: Route) => void = () => undefined;
  const delayedRoute = new Promise<Route>((resolve) => { receiveDelayedRoute = resolve; });
  await page.route("**/api/price-change?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("instrument") === "bitget:BTCUSDT"
      && url.searchParams.get("referenceTime") === "00:00") {
      receiveDelayedRoute(route);
      return;
    }
    await route.fallback();
  });
  await page.goto("/");
  const pending = await delayedRoute;
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(change).toContainText("取得中");
  await page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true }).fill("09:07");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();

  await pending.fulfill({
    json: priceChangeFixture(new URL(pending.request().url()), await browserNow(page))
  });
  await settleChartPaint(page);
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  await expect(change.getByText("+3.00%", { exact: true })).toHaveCount(0);
});

test.describe("約定騰落率のJST日付切替", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("日本時間の0時で旧基準の値を消して新しい基準を取得する", async ({ page }) => {
    const start = new Date("2026-09-10T14:59:50.000Z");
    const midnight = Date.parse("2026-09-10T15:00:00.000Z");
    await page.clock.install({ time: start });
    let receiveRolloverRoute: (route: Route) => void = () => undefined;
    const rolloverRoute = new Promise<Route>((resolve) => { receiveRolloverRoute = resolve; });
    await page.route("**/api/price-change?*", async (route) => {
      const url = new URL(route.request().url());
      const now = await browserNow(page);
      if (url.searchParams.get("instrument") === "bitget:BTCUSDT"
        && now.getTime() >= midnight) {
        receiveRolloverRoute(route);
        return;
      }
      await route.fulfill({ json: priceChangeFixture(url, now) });
    });
    await page.goto("/");
    const change = page.getByRole("region", { name: "約定価格の騰落率" });
    await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone))
      .toBe("America/Los_Angeles");

    await page.clock.fastForward(11_000);
    const pending = await rolloverRoute;
    const url = new URL(pending.request().url());
    expect(url.searchParams.get("referenceTime")).toBe("00:00");
    await expect(change.getByText("+3.00%", { exact: true })).toHaveCount(0);
    await expect(change).toContainText("取得中");
    const fixture = priceChangeFixture(url, await browserNow(page), 102);
    expect(fixture.baselineAt).toBe("2026-09-10T15:00:00.000Z");
    await pending.fulfill({ json: fixture });
    await expect(change.getByText("+0.98%", { exact: true })).toBeVisible();
    await expect(change.getByText("102", { exact: true })).toBeVisible();
  });
});

test("約定騰落率の基準足欠損と取得失敗を0%に置き換えない", async ({ page }) => {
  await page.route("**/api/price-change?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("referenceTime") === "09:07") {
      await route.fulfill({ status: 503, json: { error: "fixture_unavailable" } });
      return;
    }
    const fixture = priceChangeFixture(url, await browserNow(page));
    await route.fulfill({ json: {
      ...fixture,
      status: "unavailable",
      reason: "baseline_missing",
      baselinePrice: null,
      changePercent: null
    } satisfies DailyPriceChange });
  });
  await page.goto("/");
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(change).toContainText("基準足なし");
  await expect(change.getByText(/^[+-]?\d[\d,.]*%$/)).toHaveCount(0);

  await page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true }).fill("09:07");
  await expect(change).toContainText("値動きの取得に失敗しました (503)");
  await expect(change.getByText(/^[+-]?\d[\d,.]*%$/)).toHaveCount(0);
  await expect(change).not.toContainText("基準足なし");
});

test("約定騰落率の設定はstorageが使えなくても画面内で変更できる", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new DOMException("Storage is disabled", "SecurityError"); }
    });
  });
  await page.goto("/");
  const setting = page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true });
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(setting).toHaveValue("00:00");
  await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
  await setting.fill("09:07");
  await expect(setting).toHaveValue("09:07");
  await expect(page.getByRole("status").filter({
    hasText: "保存できないため、この画面だけに適用しています"
  })).toBeVisible();
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
});

function priceChangeFixture(url: URL, now: Date, baselinePrice?: number): DailyPriceChange {
  const versionIds: Record<string, number> = {
    "bitget:BTCUSDT": 1,
    "hyperliquid:BTC": 2,
    "bitget:ETHUSDT": 3
  };
  const venueInstrumentId = url.searchParams.get("instrument") ?? "";
  const referenceTime = url.searchParams.get("referenceTime") ?? "";
  const venueInstrumentVersionId = versionIds[venueInstrumentId];
  if (!venueInstrumentVersionId) throw new Error(`未知の騰落率fixture: ${venueInstrumentId}`);
  const baseline = baselinePrice ?? (referenceTime === "09:07" ? 110 : 100);
  return {
    venueInstrumentId,
    venueInstrumentVersionId,
    referenceTime,
    baselineAt: new Date(dailyBaselineAt(now.getTime(), referenceTime)).toISOString(),
    generatedAt: now.toISOString(),
    status: "ready",
    reason: null,
    baselinePrice: baseline,
    currentPrice: 103,
    currentCandleAt: new Date(Math.floor(now.getTime() / 60_000) * 60_000).toISOString(),
    changePercent: (103 / baseline - 1) * 100
  };
}

async function browserNow(page: Page): Promise<Date> {
  return new Date(await page.evaluate(() => Date.now()));
}

test("チャートの時間足をVenue切り替えと履歴到着後も保持する", async ({ page }) => {
  await page.goto("/");
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await chart.getByRole("button", { name: "1h", exact: true }).click();
  await expect(chart.getByRole("button", { name: "1h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );

  const historyResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/chart-history"
      && url.searchParams.get("instrument") === "hyperliquid:BTC"
      && url.searchParams.get("timeframe") === "1h";
  });
  await page.getByRole("button", { name: "BTC hyperliquidを詳細表示" }).click();
  await (await historyResponse).finished();
  await expect.poll(async () => (await readSelectionCommand())?.venueInstrumentId)
    .toBe("hyperliquid:BTC");

  await expect(chart).toContainText("hyperliquid:BTC");
  await expect(chart.getByRole("button", { name: "1h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );
  await expect(chart).toHaveAccessibleDescription(/hyperliquid:BTC 1h 120本/);
});

test("チャートのズームを市場データと履歴の定期更新で戻さない", async ({ page }) => {
  await page.clock.install();
  await page.goto("/");
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 120本/);
  const candles = chart.locator("canvas").first();
  const period = chart.getByLabel("チャート表示期間", { exact: true });
  await candles.scrollIntoViewIfNeeded();
  await settleChartPaint(page);
  const initialImage = await canvasImage(candles);
  const initialPeriod = await period.textContent();
  const bounds = await candles.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) throw new Error("ローソク足canvasの表示領域がありません");

  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.wheel(0, -400);
  await expect(period).not.toHaveText(initialPeriod ?? "");
  await page.mouse.move(0, 0);
  await expect.poll(() => canvasImage(candles)).not.toBe(initialImage);
  await settleChartPaint(page);
  const zoomedImage = await canvasImage(candles);
  const zoomedPeriod = await period.textContent();

  const response = await page.waitForResponse(
    (response) => response.url().endsWith("/api/market-data") && response.status() === 200,
    { timeout: 8_000 }
  );
  await response.finished();
  await settleChartPaint(page);
  await expect(period).toHaveText(zoomedPeriod ?? "");
  expect(await canvasImage(candles)).toBe(zoomedImage);

  const historyResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/chart-history"
      && response.status() === 200
  );
  await page.clock.fastForward(60_000);
  await (await historyResponse).finished();
  await settleChartPaint(page);
  await expect(period).toHaveText(zoomedPeriod ?? "");
  expect(await canvasImage(candles)).toBe(zoomedImage);
});

test("チャートの古い履歴応答で新しく選んだ時間足を上書きしない", async ({ page }) => {
  const now = new Date();
  let receiveDelayedRoute: (route: Route) => void = () => undefined;
  const delayedRoute = new Promise<Route>((resolve) => { receiveDelayedRoute = resolve; });
  await page.route("**/api/chart-history?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("timeframe") === "1h") {
      receiveDelayedRoute(route);
      return;
    }
    await route.fallback();
  });
  await page.goto("/");
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 120本/);
  await chart.getByRole("button", { name: "1h", exact: true }).click();
  const pending = await delayedRoute;
  await chart.getByRole("button", { name: "4h", exact: true }).click();
  await expect(chart).toHaveAccessibleDescription(/4h 120本/);

  await pending.fulfill({ json: chartHistoryFixture(new URL(pending.request().url()), now) });
  await settleChartPaint(page);
  await expect(chart.getByRole("button", { name: "4h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );
  await expect(chart).toHaveAccessibleDescription(/4h 120本/);
});

test("チャートを過去へスクロールすると履歴を追加し表示位置を保つ", async ({ page }) => {
  const now = new Date();
  let receiveOlderRoute: (route: Route) => void = () => undefined;
  const olderRoute = new Promise<Route>((resolve) => { receiveOlderRoute = resolve; });
  let firstBucket: string | null = null;
  await page.route("**/api/chart-history?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("before")) {
      receiveOlderRoute(route);
      return;
    }
    const fixture = chartHistoryFixture(url, now, 180);
    firstBucket = fixture.bars[0].bucketAt;
    await route.fulfill({ json: { ...fixture, hasMore: true, nextBefore: firstBucket } });
  });
  await page.goto("/");
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 180本/);
  const candles = chart.locator("canvas").first();
  const period = chart.getByLabel("チャート表示期間", { exact: true });
  await candles.scrollIntoViewIfNeeded();
  const bounds = await candles.boundingBox();
  if (!bounds) throw new Error("ローソク足canvasの表示領域がありません");

  const request = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/api/chart-history" && url.searchParams.has("before");
  }, { timeout: 5_000 });
  await page.mouse.move(bounds.x + bounds.width * 0.05, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.05 + 1, bounds.y + bounds.height / 2);
  await page.mouse.move(bounds.x + bounds.width * 0.55, bounds.y + bounds.height / 2, { steps: 10 });
  expect(new URL((await request).url()).searchParams.get("before")).toBe(firstBucket);
  await settleChartPaint(page);
  const scrolledEnd = (await period.textContent())?.split(" — ")[1];
  expect(scrolledEnd).toBeTruthy();
  const pending = await olderRoute;
  await pending.fulfill({ json: chartHistoryFixture(new URL(pending.request().url()), now) });

  await expect(chart).toHaveAccessibleDescription(/15m 300本/);
  await settleChartPaint(page);
  await expect(period).toContainText(` — ${scrolledEnd}`);
  await expect(chart.getByRole("button", { name: "さらに過去を読み込む" })).toHaveCount(0);
  await page.mouse.up();
  await page.mouse.move(0, 0);
});

test.describe("チャートのJST表示", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("1Dは120日分の日足を表示し日足の区切りをJSTで明示する", async ({ page }, testInfo) => {
    await page.goto("/");
    const chart = page.getByRole("region", { name: "価格・出来高" });
    const timeframes = chart.getByLabel("チャート時間足", { exact: true });
    await expect(timeframes.getByRole("button", { name: "24h", exact: true })).toHaveCount(0);
    await timeframes.getByRole("button", { name: "1D", exact: true }).click();
    await expect(chart).toHaveAccessibleDescription(/1D 120本/);
    await expect(chart.getByText("日足の区切り 09:00 JST", { exact: true })).toBeVisible();
    await expect(chart.getByLabel("チャート表示期間", { exact: true })).toContainText("JST");
    await expect(chart.getByLabel("チャート表示期間", { exact: true })).toContainText(/09:00.*09:00/);
    await chart.screenshot({ path: testInfo.outputPath("chart-1d.png") });
    await page.screenshot({ path: testInfo.outputPath("page-1d.png"), fullPage: true });

    await page.getByRole("button", { name: "ETH bitgetを詳細表示" }).click();
    await expect(chart).toHaveAccessibleDescription(/bitget:ETHUSDT 1D 120本/);
    await expect(timeframes.getByRole("button", { name: "1D", exact: true })).toHaveAttribute(
      "aria-pressed", "true"
    );
  });
});

function chartHistoryFixture(url: URL, now: Date, count = 120) {
  const timeframe = url.searchParams.get("timeframe") as Timeframe;
  const seconds = { "5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400, "24h": 86_400 }[timeframe];
  if (!seconds || !url.searchParams.get("instrument")) {
    throw new Error(`履歴要求のinstrument/timeframeが不正です: ${url.pathname}${url.search}`);
  }
  return {
    venueInstrumentId: url.searchParams.get("instrument"),
    timeframe,
    generatedAt: now.toISOString(),
    bars: Array.from({ length: count }, (_, index) => {
      const open = 64_900 + index * 2 + Math.sin(index / 5) * 50;
      const end = url.searchParams.get("before");
      const endMs = end ? Date.parse(end) : now.getTime();
      const bucketAt = Math.floor(endMs / (seconds * 1_000)) * seconds * 1_000
        - (count - index) * seconds * 1_000;
      return {
        bucketAt: new Date(bucketAt).toISOString(),
        open,
        high: open + 100,
        low: open - 50,
        close: open + 30,
        volumeBase: 10,
        volumeNotional: 650_000,
        complete: true
      };
    }),
    hasMore: false,
    nextBefore: null
  };
}

async function canvasImage(canvas: Locator) {
  const image = await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL());
  return createHash("sha256").update(image).digest("hex");
}

async function settleChartPaint(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function publishArtifacts(now: Date) {
  const generatedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + 5 * 60_000).toISOString();
  const universe: UniverseSnapshotArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "partial",
    qualityReasons: ["contains_non_ready_instruments"],
    parityAssumption: {
      code: "usd_usdc_usdt_reference_only",
      appliedTo: "reference_mark_median_only",
      statement: "USD、USDC、USDTは参考中央値だけ等価扱い"
    },
    items: [
      universeInstrument({
        venue: "bitget",
        sourceSymbol: "BTCUSDT",
        versionId: 1,
        baseAsset: "BTC",
        quoteAsset: "USDT",
        settleAsset: "USDT",
        collateralAsset: "USDT",
        groupId: "crypto:BTC:linear-perp",
        markPrice: 65_000,
        generatedAt,
        medianVenues: ["bitget", "hyperliquid"],
        medianValue: 65_001
      }),
      universeInstrument({
        venue: "hyperliquid",
        sourceSymbol: "BTC",
        versionId: 2,
        baseAsset: "BTC",
        quoteAsset: "USD",
        settleAsset: "USDC",
        collateralAsset: "USDC",
        groupId: "crypto:BTC:linear-perp",
        markPrice: 65_002,
        generatedAt,
        medianVenues: ["bitget", "hyperliquid"],
        medianValue: 65_001
      }),
      universeInstrument({
        venue: "bitget",
        sourceSymbol: "ETHUSDT",
        versionId: 3,
        baseAsset: "ETH",
        quoteAsset: "USDT",
        settleAsset: "USDT",
        collateralAsset: "USDT",
        groupId: "crypto:ETH:linear-perp",
        markPrice: 3_500,
        generatedAt,
        medianVenues: ["bitget"],
        medianValue: null
      })
    ]
  };
  const chart: MarketChartArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
    venueInstrumentId: "bitget:BTCUSDT",
    timeframes: [
      {
        timeframe: "15m",
        seconds: 900,
        bars: [
          {
            bucketAt: new Date(now.getTime() - 15 * 60_000).toISOString(),
            open: 64_900,
            high: 65_050,
            low: 64_850,
            close: 65_000,
            volumeBase: 10,
            volumeNotional: 650_000,
            tradeCount: 20,
            finality: "confirmed",
            sourceAt: generatedAt,
            observedAt: generatedAt,
            sourceBarCount: 15,
            expectedSourceBarCount: 15,
            complete: true,
            qualityReasons: []
          }
        ]
      }
    ]
  };
  const selected: SelectedMarketArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
    disclaimers: {
      includesFees: false,
      predictsFutureImpact: false,
      confirmsOrderAvailability: false,
      statement: "Reference onlyの板上概算です。"
    },
    selection: {
      selectionId: "e2e-selection",
      groupId: "crypto:BTC:linear-perp",
      primaryVenueInstrumentId: "bitget:BTCUSDT",
      expiresAt,
      instruments: [
        selectedInstrument("bitget", "BTCUSDT", "USDT", 1, 65_000, generatedAt),
        selectedInstrument("hyperliquid", "BTC", "USD", 2, 65_002, generatedAt)
      ],
      trades: [
        {
          venueInstrumentId: "bitget:BTCUSDT",
          venueInstrumentVersionId: 1,
          venue: "bitget",
          sourceSymbol: "BTCUSDT",
          tradeId: "trade-1",
          side: "buy",
          price: 65_000,
          sizeBase: 0.01,
          sourceAt: null,
          receivedAt: generatedAt
        }
      ]
    }
  };
  const service: MarketServiceStateArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "partial",
    qualityReasons: ["artifact_write_failure"],
    collectors: [],
    catalog: {
      status: "ready",
      latestAt: generatedAt,
      ageSeconds: 1,
      maxAgeSeconds: 1_800,
      errorCode: null
    },
    l1: {
      status: "ready",
      latestAt: generatedAt,
      ageSeconds: 1,
      maxAgeSeconds: 120,
      errorCode: null
    },
    artifacts: [
      artifactState("universe-snapshot.json", generatedAt),
      artifactState("market-chart.json", generatedAt),
      artifactState("selected-market.json", generatedAt),
      artifactState("service-state.json", generatedAt)
    ]
  };

  await Promise.all([
    atomicWrite(resolve(artifactRoot, "universe-snapshot.json"), universe),
    atomicWrite(resolve(artifactRoot, "market-chart.json"), chart),
    atomicWrite(resolve(artifactRoot, "selected-market.json"), selected)
  ]);
  await atomicWrite(resolve(artifactRoot, "service-state.json"), service);
}

function universeInstrument(input: {
  venue: "bitget" | "hyperliquid";
  sourceSymbol: string;
  versionId: number;
  baseAsset: string;
  quoteAsset: string;
  settleAsset: string;
  collateralAsset: string;
  groupId: string;
  markPrice: number;
  generatedAt: string;
  medianVenues: ("bitget" | "hyperliquid")[];
  medianValue: number | null;
}): UniverseInstrumentArtifact {
  const instrumentId = `${input.venue}:${input.sourceSymbol}`;
  return {
    venueInstrumentId: instrumentId,
    venueInstrumentVersionId: input.versionId,
    groupId: input.groupId,
    mappingMethod: "exact_base_heuristic",
    venue: input.venue,
    sourceSymbol: input.sourceSymbol,
    baseAsset: input.baseAsset,
    quoteAsset: input.quoteAsset,
    settleAsset: input.settleAsset,
    collateralAsset: input.collateralAsset,
    active: true,
    marketType: "linear_perpetual",
    executionModel: "clob",
    catalog: {
      sourceKind: "native_rest",
      endpoint: `/e2e/catalog/${input.venue}`,
      documentationUrl: null,
      payloadHash: `catalog-${instrumentId}`,
      observedAt: input.generatedAt,
      sourceAt: null
    },
    quality: "ready",
    qualityReasons: [],
    ageSeconds: 1,
    collectorRunId: "e2e-run",
    cycleAt: input.generatedAt,
    observedAt: input.generatedAt,
    sourceAt: null,
    sourcePayloadHash: `l1-${instrumentId}`,
    errorCode: null,
    markPrice: input.markPrice,
    referencePrice: input.markPrice + 1,
    referencePriceKind: input.venue === "hyperliquid" ? "oracle" : "index",
    bestBid: input.markPrice - 1,
    bestAsk: input.markPrice + 1,
    fundingRateRaw: 0.0001,
    fundingIntervalSeconds: input.venue === "hyperliquid" ? 3_600 : 28_800,
    fundingRatePerHour: 0.0000125,
    nextFundingAt: input.generatedAt,
    openInterestRaw: 10,
    openInterestRawUnit: "base",
    openInterestBase: 10,
    openInterestNotional: input.markPrice * 10,
    volume24hRaw: input.markPrice * 100,
    volume24hUnit: "quote",
    referenceMarkMedian: {
      status: input.medianValue === null ? "unavailable" : "ready",
      value: input.medianValue,
      venueCount: input.medianVenues.length,
      venues: input.medianVenues,
      cycleAt: input.generatedAt,
      maxAgeSeconds: 1,
      skewSeconds: 0,
      unavailableReason: input.medianValue === null ? "insufficient_venues" : null,
      parityAssumptionCode: "usd_usdc_usdt_reference_only"
    }
  };
}

function selectedInstrument(
  venue: "bitget" | "hyperliquid",
  sourceSymbol: string,
  quoteAsset: string,
  versionId: number,
  markPrice: number,
  generatedAt: string
) {
  return {
    venueInstrumentId: `${venue}:${sourceSymbol}`,
    venueInstrumentVersionId: versionId,
    venue,
    sourceSymbol,
    quoteAsset,
    depthReceivedAt: generatedAt,
    depthAgeSeconds: 1,
    quality: "ready" as const,
    qualityReasons: [],
    bids: [
      { price: markPrice - 1, sizeBase: 1 },
      { price: markPrice - 2, sizeBase: 2 }
    ],
    asks: [
      { price: markPrice + 1, sizeBase: 1 },
      { price: markPrice + 2, sizeBase: 2 }
    ],
    bookWalks: [100, 500, 1_000].map((notionalQuote, index) => ({
      notionalQuote,
      buy: {
        baseSize: notionalQuote / markPrice,
        averagePrice: markPrice + index + 1,
        topPriceImpactBps: index + 0.1
      },
      sell: {
        baseSize: notionalQuote / markPrice,
        averagePrice: markPrice - index - 1,
        topPriceImpactBps: index + 0.1
      },
      buyUnavailableReason: null,
      sellUnavailableReason: null,
      includesFees: false as const,
      predictsFutureImpact: false as const,
      confirmsOrderAvailability: false as const
    }))
  };
}

function artifactState(name: string, generatedAt: string) {
  return { name, status: "ready" as const, generatedAt, errorCode: null };
}

async function atomicWrite(path: string, value: unknown) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value)}\n`, "utf-8");
  await rename(temporary, path);
}

async function readSelectionCommand(): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(await readFile(selectionPath, "utf-8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}
