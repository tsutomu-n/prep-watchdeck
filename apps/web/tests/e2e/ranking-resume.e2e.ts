import { expect, test, type Page } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

const NOW = Date.parse("2026-10-09T03:00:15Z");
const cutoff = NOW - 15_000;
const menu = (page: Page) => page.getByRole("navigation", { name: "メインメニュー" });

async function prepare(page: Page) {
  await page.clock.install({ time: NOW });
  await page.route("**/api/user-workspace", route => route.fulfill({ json: {
    schemaVersion: 1, revision: 0, favorites: [], savedViews: []
  } }));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({
    contentType: "application/javascript", body: ""
  }));
}

test("設定から戻ると再取得待ちでも一覧・選択・表示件数・scrollを復元し、古い値を明示する", async ({ page }) => {
  await prepare(page);
  let hold = false;
  let requests = 0;
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/market-data", route => route.fulfill({ status: 503, json: { error: "unavailable" } }));
  await page.route("**/api/rankings?**", async route => {
    requests += 1;
    if (hold) {
      await pending;
      return route.fulfill({ status: 503, json: { error: "unavailable" } });
    }
    const payload = rankingFixture(new URL(route.request().url()).searchParams, cutoff);
    const seed = payload.rows.find(row => row.asset === "BTC")!;
    payload.rows = Array.from({ length: 110 }, (_, index) => ({
      ...seed, id: `asset:TOKEN${index}`, asset: `TOKEN${String(index).padStart(3, "0")}`,
      rank: index + 1, widget: { ...seed.widget, status: "unsupported" as const, symbol: null }
    }));
    payload.coverage.rows = payload.coverage.ranked = 110;
    await route.fulfill({ json: payload });
  });
  try {
    await page.goto("/?mode=reference");
    await expect(page.getByTestId("ranking-row")).toHaveCount(50);
    await page.getByLabel("ランキングの銘柄検索").fill("TOKEN");
    await page.getByRole("button", { name: /さらに50件を表示/ }).click();
    await expect(page.getByTestId("ranking-row")).toHaveCount(100);
    await page.locator('[data-asset="TOKEN039"] .select-row').click();
    const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
    if (await back.isVisible()) { await back.click(); await expect(back).toBeHidden(); }
    await page.locator(".table-scroll").evaluate(element => { element.scrollTop = 640; });
    await expect.poll(() => page.locator(".table-scroll").evaluate(element => element.scrollTop)).toBe(640);
    await menu(page).getByRole("link", { name: "設定", exact: true }).click();
    await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
    const before = requests;
    hold = true;
    await page.clock.fastForward(180_000);
    expect(requests).toBe(before);
    await menu(page).getByRole("link", { name: "ランキング", exact: true }).click();
    await expect.poll(() => requests).toBeGreaterThan(before);
    await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("TOKEN");
    await expect(page.getByTestId("ranking-row")).toHaveCount(100);
    await expect(page.locator('[data-asset="TOKEN039"] .select-row')).toHaveAttribute("aria-pressed", "true");
    await expect.poll(() => page.locator(".table-scroll").evaluate(element => element.scrollTop)).toBe(640);
    await expect(page.getByText("前回取得した一覧を表示しています。最新データを確認中です。")).toBeVisible();
    await expect(page.getByText(/更新が停止しています。表示値は/)).toBeVisible();
    release();
    await expect(page.getByRole("button", { name: "再試行", exact: true })).toBeVisible();
    await expect(page.getByTestId("ranking-row")).toHaveCount(100);
    await expect(page.getByTestId("volume-spotlight")).toHaveCount(0);
  } finally { release(); }
});

test("復帰時も変更した初期設定と明示URLを優先する", async ({ page }) => {
  await prepare(page);
  await page.route("**/api/rankings?**", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams, cutoff)
  }));
  await page.goto("/?mode=reference");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await page.getByLabel("ランキングの銘柄検索").fill("BTC");
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  await page.getByLabel("ランキングの初期比較期間").selectOption("15m");
  await menu(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("15m");
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("");
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  const link = menu(page).getByRole("link", { name: "ランキング", exact: true });
  await link.evaluate(element => element.setAttribute("href", "/?mode=reference&period=24h&order=turnover&q=ETH"));
  await link.click();
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("24h");
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("ETH");
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  await expect(page.getByTestId("ranking-row")).toHaveAttribute("data-asset", "ETH");
});

test("mobileで詳細と一覧から設定を往復しても同じ履歴の検索・条件・選択を保持する", async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 1440) > 960, "mobile detail history only");
  await prepare(page);
  await page.route("**/api/rankings?**", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams, cutoff)
  }));
  await page.route("**/api/market-data", route => route.fulfill({ status: 503, json: { error: "unavailable" } }));
  await page.goto("/?mode=reference");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await page.getByLabel("ランキングの銘柄検索").fill("BTC");
  const selected = page.locator('[data-asset="BTC"] .select-row');
  const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  await selected.click();
  await expect(back).toBeVisible();
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  await page.goBack();
  await expect(back).toBeVisible();
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await back.click();
  await expect(back).toBeHidden();
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("ランキングの銘柄検索")).toBeVisible();
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("BTC");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("1h");
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  await expect(selected).toHaveAttribute("aria-pressed", "true");
  await expect(back).toBeHidden();

  // A direct selected URL creates both history entries before any row is clicked.
  await page.goto("/?mode=reference&selected=asset:BTC");
  await expect(back).toBeVisible();
  await back.click();
  await expect(back).toBeHidden();
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await page.getByLabel("ランキングの銘柄検索").fill("BTC");
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("ランキングの銘柄検索")).toBeVisible();
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("BTC");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("daily");
  await expect(back).toBeHidden();

  // The menu can clear page.state while reusing this component; selecting again
  // must restore the shared history identity before another settings round trip.
  await selected.click();
  await expect(back).toBeVisible();
  await menu(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(back).toBeHidden();
  await selected.click();
  await expect(back).toBeVisible();
  await menu(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  await page.goBack();
  await expect(back).toBeVisible();
  await back.click();
  await expect(back).toBeHidden();
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("BTC");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("daily");
  await expect(selected).toHaveAttribute("aria-pressed", "true");
});

test("取扱い契約は詳細を開いてから取得し、更新で契約版が変われば移動先を無効にする", async ({ page }) => {
  await prepare(page);
  let nativeRequests = 0;
  let version = 1;
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/rankings?**", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams, cutoff)
  }));
  await page.route("**/api/market-data", async route => {
    nativeRequests += 1;
    await pending;
    await route.fulfill({ json: { universe: {
      generatedAt: new Date(NOW).toISOString(), items: [{ active: true, venue: "bitget",
        venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: version, sourceSymbol: "BTCUSDT" }]
    } } });
  });
  try {
    await page.goto("/?mode=reference");
    await expect(page.getByTestId("ranking-row").first()).toBeVisible();
    expect(nativeRequests).toBe(0);
    await page.locator('[data-asset="BTC"] .select-row').click();
    await expect(page.getByText("現在の取扱い契約を確認しています。")).toBeVisible();
    await expect.poll(() => nativeRequests).toBe(1);
    release();
    const destination = page.getByRole("link", { name: "Bitget · BTCUSDT を確認", exact: true });
    await expect(destination).toBeVisible();
    version = 2;
    await page.clock.fastForward(15_000);
    await expect.poll(() => nativeRequests).toBeGreaterThan(1);
    await expect(destination).toHaveCount(0);
    await expect(page.getByText("現在の取扱い情報で、同一契約として確認できる移動先がありません。")).toBeVisible();
  } finally { release(); }
});
