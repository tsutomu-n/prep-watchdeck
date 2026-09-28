import { expect, test, type Page, type Route } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

const FIXTURE_NOW = Date.parse("2026-09-12T00:31:15Z");
const widgetStub = `
const config = JSON.parse(document.currentScript.textContent);
const symbol = new URLSearchParams(location.search).get('tvwidgetsymbol') || config.symbol;
const host = document.querySelector('.tradingview-widget-container__widget');
host.innerHTML = '<div data-testid="stub-contract"></div><canvas data-testid="stub-candle" width="700" height="320"></canvas>';
host.querySelector('div').textContent = symbol + ' / ' + config.interval;
const ctx = host.querySelector('canvas').getContext('2d');
ctx.fillStyle = '#172318'; ctx.fillRect(0, 0, 700, 320);
ctx.fillStyle = '#9beaa7'; ctx.fillRect(340, 90, 12, 110);
`;

async function prepare(page: Page, options: { denyStorage?: boolean; stale?: boolean; removedAssets?: Set<string> } = {}) {
  const errors: string[] = [];
  const apiQueries: string[] = [];
  let widgets = 0;
  let coreRequests = 0;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.clock.install({ time: FIXTURE_NOW });
  if (options.denyStorage) await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("disabled", "SecurityError"); } });
  });
  await page.route("**/api/market-data**", (route) => { coreRequests += 1; return route.abort(); });
  await page.route("**/api/selection**", (route) => { coreRequests += 1; return route.abort(); });
  await page.route("https://s3.tradingview.com/**", async (route) => {
    widgets += 1;
    await route.fulfill({ contentType: "application/javascript", body: widgetStub });
  });
  await page.route("**/api/rankings?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    apiQueries.push(query.toString());
    const now = await page.evaluate(() => Date.now());
    const payload = rankingFixture(query, Math.floor(now / 60_000) * 60_000 - (options.stale ? 600_000 : 0));
    if (options.stale) { payload.stale = true; payload.status = "stale"; }
    if (options.removedAssets?.size) {
      payload.mapVersion = "updated-map";
      payload.rows = payload.rows.filter((row) => !options.removedAssets!.has(row.asset));
    }
    await route.fulfill({ json: payload });
  });
  return { errors, apiQueries, widgets: () => widgets, coreRequests: () => coreRequests };
}

test("全対象の条件変更、選択維持、単一Widgetと時間足を扱う", async ({ page }) => {
  const probe = await prepare(page);
  await page.goto("/rankings?tvwidgetsymbol=NASDAQ%3AAAPL");
  const btc = page.getByTestId("ranking-row").filter({ hasText: "BTC" });
  await expect(btc).toBeVisible();
  await btc.getByRole("button").click();
  const chart = page.getByTestId("ranking-chart");
  await expect(chart).toHaveAttribute("data-symbol", "BYBIT:BTCUSDT.P");
  const frame = chart.locator("iframe").contentFrame();
  await expect(frame.getByTestId("stub-contract")).toHaveText("BYBIT:BTCUSDT.P / 15");
  await page.getByLabel("ランキングチャートの時間足").selectOption("60");
  await expect(frame.getByTestId("stub-contract")).toHaveText("BYBIT:BTCUSDT.P / 60");
  const element = await chart.locator("iframe").elementHandle();
  const widgetCount = probe.widgets();
  await page.getByLabel("ランキングの並び順").selectOption("losers");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "SOL");
  await expect(page.getByText("選択銘柄は現在の一覧条件の対象外です。選択は維持しています。")).toBeVisible();
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "SOL");
  await page.clock.fastForward(65_000);
  await expect.poll(() => probe.apiQueries.length).toBeGreaterThanOrEqual(4);
  expect(await element!.evaluate((node) => node.isConnected)).toBe(true);
  expect(probe.widgets()).toBe(widgetCount);
  await expect(frame.getByTestId("stub-contract")).toHaveText("BYBIT:BTCUSDT.P / 60");
  expect(probe.coreRequests()).toBe(0);
  expect(probe.errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("期間と下限、JST設定保存、順位外・Widget未対応の理由を表示する", async ({ page }) => {
  const probe = await prepare(page);
  await page.goto("/rankings");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "BTC");
  await page.getByLabel("ランキングの並び順").selectOption("turnover");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "ETH");
  await page.getByLabel("売買代金の下限", { exact: true }).fill("1000000");
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await page.getByLabel("騰落率の基準時刻（日本時間）").fill("09:30");
  await page.getByLabel("騰落率の基準時刻（日本時間）").blur();
  await expect.poll(() => probe.apiQueries.at(-1)).toContain("dailyReferenceJst=09%3A30");
  await page.reload();
  await expect(page.getByLabel("騰落率の基準時刻（日本時間）")).toHaveValue("09:30");
  await page.getByLabel("順位外・未対応も表示").check();
  await expect(page.getByText("期間内の履歴不足", { exact: true }).first()).toBeVisible();
  await page.getByTestId("ranking-row").filter({ hasText: "NOCHART" }).getByRole("button").click();
  await expect(page.getByText("この参照契約のWidgetは利用できません")).toBeVisible();
  expect(probe.errors).toEqual([]);
});

test("保存不可でも操作を続け、古い取得時刻を隠さない", async ({ page }) => {
  const probe = await prepare(page, { denyStorage: true, stale: true });
  await page.goto("/rankings");
  await expect(page.getByText(/更新が停止しています。表示値は/)).toBeVisible();
  await page.getByLabel("騰落率の基準時刻（日本時間）").fill("08:45");
  await page.getByLabel("騰落率の基準時刻（日本時間）").blur();
  await expect(page.getByText("保存できないため、この画面だけに適用しています")).toBeVisible();
  await page.getByTestId("ranking-row").filter({ hasText: "BTC" }).getByRole("button").click();
  await expect(page.getByTestId("ranking-chart")).toHaveAttribute("data-symbol", "BYBIT:BTCUSDT.P");
  expect(probe.errors).toEqual([]);
});

test("新しい期間へ切り替えた後に届く旧要求を採用しない", async ({ page }) => {
  const probe = await prepare(page);
  await page.goto("/rankings");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "BTC");
  let release!: () => void;
  let requested = false;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/rankings?**", async (route) => {
    const query = new URL(route.request().url()).searchParams;
    if (query.get("period") !== "1h") return route.fallback();
    requested = true;
    await held;
    await route.fulfill({ json: rankingFixture(query, FIXTURE_NOW - 60_000) });
  });
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await expect.poll(() => requested).toBe(true);
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await expect.poll(() => probe.apiQueries.at(-1)).toContain("period=daily");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "BTC");
  release();
  await page.clock.fastForward(100);
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("daily");
  await expect(page.getByText("09/12 00:00 → 09/12 09:31", { exact: true })).toBeVisible();
  expect(probe.errors).toEqual([]);
});

test("対応表から削除された選択は名前を維持し、旧Widgetを停止する", async ({ page }) => {
  const removedAssets = new Set<string>();
  const probe = await prepare(page, { removedAssets });
  await page.goto("/rankings");
  await page.getByTestId("ranking-row").filter({ hasText: "BTC" }).getByRole("button").click();
  await expect(page.getByTestId("ranking-chart")).toHaveAttribute("data-symbol", "BYBIT:BTCUSDT.P");
  removedAssets.add("BTC");
  await page.clock.fastForward(65_000);
  await expect(page.getByText("選択銘柄は更新後の対応表にありません。選択名を維持し、チャートを停止しています。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await expect(page.getByTestId("ranking-chart")).toHaveCount(0);
  const widgetCount = probe.widgets();
  let release!: () => void;
  let held: Promise<void>;
  let requested = 0;
  const failedRefresh = async (route: Route) => {
    requested += 1;
    await held;
    await route.fulfill({ status: 503, json: { status: "unavailable" } });
  };
  await page.route("**/api/rankings?**", failedRefresh);
  const changes = [
    () => page.getByLabel("ランキングの比較期間").selectOption("1h"),
    () => page.getByLabel("ランキングの並び順").selectOption("turnover"),
    () => page.getByLabel("売買代金の下限", { exact: true }).fill("1000000")
  ];
  for (const [index, change] of changes.entries()) {
    held = new Promise<void>((resolve) => { release = resolve; });
    try {
      await change();
      await expect.poll(() => requested).toBe(index + 1);
      await expect(page.getByTestId("ranking-chart")).toHaveCount(0);
      await expect(page.getByText("選択銘柄は更新後の対応表にありません。選択名を維持し、チャートを停止しています。")).toBeVisible();
    } finally { release(); }
    await expect(page.getByText(/ランキングの更新を待っています。専用収集/)).toBeVisible();
    await expect(page.getByTestId("ranking-chart")).toHaveCount(0);
    expect(probe.widgets()).toBe(widgetCount);
  }
  await page.unroute("**/api/rankings?**", failedRefresh);
  await page.getByRole("button", { name: "再試行", exact: true }).click();
  await page.getByTestId("ranking-row").filter({ hasText: "ETH" }).getByRole("button").click();
  await expect(page.getByTestId("ranking-chart")).toHaveAttribute("data-symbol", "BYBIT:ETHUSDT.P");
  expect(probe.errors).toEqual([]);
});
