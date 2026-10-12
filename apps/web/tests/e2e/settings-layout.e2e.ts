import { expect, test, type Page } from "@playwright/test";
import type { UserWorkspace } from "../../src/lib/server/user-workspace-repository";
import { discoverySummaryFixture } from "../../src/lib/discovery/discovery-test-fixture";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

async function prepare(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] }
  }));
  await page.route("**/api/discovery-summary", route => route.fulfill({
    json: { ...discoverySummaryFixture(), rows: [] }
  }));
  await page.route("**/api/decisions", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, decisions: [] }
  }));
  await page.route("**/api/rankings?**", route => {
    const data = rankingFixture(new URL(route.request().url()).searchParams,
      Math.floor(Date.now() / 60_000) * 60_000);
    const row = data.rows.find(item => item.asset === "BTC")!;
    data.rows.push(...Array.from({ length: 40 }, (_, i) => ({
      ...row, id: `asset:EXTRA${i}`, asset: `EXTRA${i}`, rank: i + 10
    })));
    return route.fulfill({ json: data });
  });
  return errors;
}

test("Hyperliquidモードは取扱い銘柄を絞り、比較条件と参照チャートを保持する", async ({ page }, testInfo) => {
  const errors = await prepare(page);
  await page.route("**/api/rankings?**", route => {
    const data = rankingFixture(new URL(route.request().url()).searchParams);
    for (const row of data.rows) {
      const venue = row.asset === "BTC" || row.asset === "MISSING" ? "hyperliquid" : "bitget";
      row.venues = [venue];
      row.originals = [{ ...row.originals[0], venue,
        instrumentId: `${venue}:${row.asset}`, symbol: row.asset }];
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/?mode=reference&period=1h&order=turnover");
  const modes = page.getByRole("group", { name: "ランキングの取引所モード" });
  const all = modes.getByRole("button", { name: "すべて", exact: true });
  const hyperliquid = modes.getByRole("button", { name: "Hyperliquid", exact: true });
  const rows = page.getByTestId("ranking-row");
  const btc = rows.filter({ has: page.locator("strong", { hasText: /^BTC$/ }) });
  await expect(rows).toHaveCount(4);
  const rank = await btc.locator(".rank").innerText();
  const change = await btc.locator(".change").innerText();
  const turnover = await btc.locator(".turnover > span[title]").innerText();
  await expect(all).toHaveAttribute("aria-pressed", "true");
  await rows.filter({ hasText: "ETH" }).locator("button.select-row").click();
  const chart = page.getByTestId("ranking-chart");
  await page.getByLabel("ランキングチャートの時間足").selectOption("60");
  await expect(chart).toHaveAttribute("data-symbol", "BYBIT:ETHUSDT.P");
  const frame = await chart.locator("iframe").elementHandle();
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    await page.getByRole("button", { name: "一覧へ戻る", exact: true }).click();
  }
  await expect(page.locator(".ranking-conditions")).not.toHaveAttribute("open");
  await hyperliquid.focus();
  await hyperliquid.press("Space");
  await expect(hyperliquid).toHaveAttribute("aria-pressed", "true");
  await expect(all).toHaveAttribute("aria-pressed", "false");
  await expect(rows).toHaveCount(1);
  await expect(btc).toBeVisible();
  await expect(btc.locator(".rank")).toHaveText(rank, { useInnerText: true });
  await expect(btc.locator(".change")).toHaveText(change, { useInnerText: true });
  await expect(btc.locator(".turnover > span[title]")).toHaveText(turnover, { useInnerText: true });
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("1h");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await expect(page.getByLabel("取扱い取引所")).toHaveValue("hyperliquid");
  await expect(page.getByTestId("volume-spotlight").getByTestId("relative-volume-signal")).toHaveCount(1);
  await expect(page.getByTestId("volume-spotlight")).toContainText("BTC");
  await expect(page.getByText("Hyperliquidの24時間売買代金を併記します。順位・騰落率・参照売買代金はBybit／Binanceのデータです。", { exact: true })).toBeVisible();
  await expect(chart).toHaveAttribute("data-symbol", "BYBIT:ETHUSDT.P");
  await expect(page.getByLabel("ランキングチャートの時間足")).toHaveValue("60");
  expect(await frame!.evaluate(node => node.isConnected)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("hyperliquid-mode.png") });

  await page.locator(".ranking-conditions > summary").click();
  await page.getByLabel("取扱い取引所").selectOption("bitget");
  await expect(hyperliquid).toHaveAttribute("aria-pressed", "false");
  await expect(all).toHaveAttribute("aria-pressed", "false");
  await expect(rows).toHaveCount(3);
  await all.click();
  await expect(all).toHaveAttribute("aria-pressed", "true");
  await expect(rows).toHaveCount(4);
  await page.goto("/rankings?venue=hyperliquid&period=1h&order=turnover");
  await expect(hyperliquid).toHaveAttribute("aria-pressed", "true");
  await expect(rows).toHaveCount(1);
  expect(errors).toEqual([]);
});

test("設定を一か所で変更し市場へ反映、詳細条件を閉じたまま上位を読める", async ({ page }) => {
  const errors = await prepare(page);
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "メインメニュー" });
  await nav.getByRole("link", { name: "設定", exact: true }).click();
  await page.getByLabel("配色", { exact: true }).selectOption("paper-ledger");
  await page.getByLabel("フォント", { exact: true }).selectOption("terminal");
  await page.getByLabel("騰落率の基準時刻（日本時間）").fill("09:30");
  await page.getByLabel("騰落率の基準時刻（日本時間）").blur();
  await nav.getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-color-scheme", "paper-ledger");
  await expect(page.locator("html")).toHaveAttribute("data-font-scheme", "terminal");
  await expect(page.getByLabel("フォント", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("騰落率の基準時刻（日本時間）")).toHaveCount(0);
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await expect(page.getByText(/JST 09:30/).first()).toBeVisible();
  const conditions = page.locator("details").filter({ has: page.locator("summary", { hasText: /^ランキング条件/ }) });
  await expect(conditions).not.toHaveAttribute("open");
  await expect(page.getByTestId("discovery-workflow")).toContainText("現在の成立候補なし");
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    const candidates = page.getByTestId("volume-spotlight").getByTestId("relative-volume-signal");
    await expect(candidates.nth(0)).toContainText("BTC");
    await expect(candidates.nth(1)).toContainText("SOL");
    await expect(candidates.nth(1)).toBeInViewport();
    expect(await page.getByTestId("ranking-row").first().evaluate(el => el.getBoundingClientRect().top)).toBeLessThan(844);
    expect(await page.locator(".ranking-list table").evaluate(el => el.getBoundingClientRect().width)).toBeLessThanOrEqual(390);
  }
  await conditions.locator("summary").click();
  await page.getByLabel("売買代金の下限", { exact: true }).fill("1000000");
  await conditions.locator("summary").click();
  await expect(page.getByText(/1,000,000/).first()).toBeVisible();
  await page.reload();
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await expect(page.getByText(/JST 09:30/).first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("スマホ詳細から戻って一覧位置とfocusを復元しPCは左右表示を維持する", async ({ page }) => {
  const errors = await prepare(page);
  await page.goto("/rankings");
  const row = page.getByTestId("ranking-row").filter({ hasText: "EXTRA10" });
  const scroller = page.locator(".ranking-list .table-scroll");
  await expect(row).toBeAttached();
  await scroller.evaluate(el => el.scrollTop = 250);
  const selectedButton = row.locator("button.select-row");
  await selectedButton.scrollIntoViewIfNeeded();
  const listTop = await scroller.evaluate(el => el.scrollTop);
  expect(listTop).toBeGreaterThan(0);
  await selectedButton.click();
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    await expect(page.locator(".ranking-list")).toBeHidden();
    await expect(page.getByRole("button", { name: "一覧へ戻る", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "一覧へ戻る", exact: true }).click();
    await expect(page.locator(".ranking-list")).toBeVisible();
    await expect(selectedButton).toBeFocused();
    await expect.poll(() => scroller.evaluate(el => el.scrollTop)).toBeCloseTo(listTop, 0);
    await selectedButton.click();
    await page.goBack();
    await expect(selectedButton).toBeFocused();
    await page.goto("/?mode=reference&selected=asset:BTC");
    await expect.poll(() => errors).toEqual([]);
    await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "一覧へ戻る", exact: true }).click();
    await expect(page.locator('[data-testid="ranking-row"][data-asset="BTC"] button.select-row')).toBeFocused();
  } else {
    await expect(page.locator(".ranking-list")).toBeVisible();
    await expect(page.getByTestId("ranking-chart")).toBeVisible();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("保存不可のJST設定も同じ閲覧中のページ移動で保持する", async ({ page }) => {
  const errors = await prepare(page);
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("disabled", "SecurityError"); } });
  });
  let release!: () => void;
  const hydration = new Promise<void>(resolve => { release = resolve; });
  await page.route(/\/_app\/immutable\/.*\.js(?:\?.*)?$/, async route => {
    await hydration;
    await route.continue();
  });
  try {
    await page.goto("/settings", { waitUntil: "commit" });
    const setting = page.getByLabel("騰落率の基準時刻（日本時間）");
    await expect(setting).toBeVisible();
    await expect(setting).toBeDisabled();
    release();
    await expect(setting).toBeEnabled();
    await setting.fill("08:45");
    await setting.blur();
    await expect(setting).toHaveValue("08:45");
    await expect(page.getByText(/保存できない/)).toBeVisible();
    await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "ランキング", exact: true }).click();
    await page.getByLabel("ランキングの比較期間").selectOption("daily");
    await expect(page.getByText(/JST 08:45/).first()).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    release();
  }
});

test("目的別の表示は条件を切り替え、取扱い取引所と選択チャートを保持する", async ({ page }, testInfo) => {
  const errors = await prepare(page);
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({
    contentType: "application/javascript",
    body: `
      const config = JSON.parse(document.currentScript.textContent);
      document.querySelector('.tradingview-widget-container__widget').textContent = config.symbol + ' / ' + config.interval;
    `
  }));
  let workspace: UserWorkspace = {
    schemaVersion: 2, revision: 1, savedViews: [], pins: [],
    favorites: [{ kind: "reference", id: "asset:BTC", referenceKey: "bybit:BTCUSDT:fixture-v1",
      originals: ["bitget:BTCUSDT:1"] }]
  };
  await page.route("**/api/user-workspace", route => {
    if (route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      expect(command.action).toBe("saveView");
      workspace = { ...workspace, revision: workspace.revision + 1,
        savedViews: [{ id: command.id, name: command.name, view: command.view }] };
    }
    return route.fulfill({ json: workspace });
  });
  await page.goto("/");
  const purposes = page.getByRole("group", { name: "目的別の表示" });
  const whole = purposes.getByRole("button", { name: "市場全体", exact: true });
  const movement = purposes.getByRole("button", { name: "短期の値動き", exact: true });
  const activity = purposes.getByRole("button", { name: "売買代金の増加", exact: true });
  const favorites = purposes.getByRole("button", { name: "お気に入り監視", exact: true });
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("24h");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await expect(whole).toHaveAttribute("aria-pressed", "true");

  const btc = page.locator('[data-testid="ranking-row"][data-asset="BTC"]');
  await btc.locator("button.select-row").click();
  const chart = page.getByTestId("ranking-chart");
  await page.getByLabel("ランキングチャートの時間足").selectOption("60");
  const frame = chart.locator("iframe").contentFrame();
  await expect(frame.locator(".tradingview-widget-container__widget")).toHaveText("BYBIT:BTCUSDT.P / 60");
  const originalFrame = await chart.locator("iframe").elementHandle();
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    await page.getByRole("button", { name: "一覧へ戻る", exact: true }).click();
  }

  await page.locator(".ranking-conditions > summary").click();
  await page.getByLabel("取扱い取引所").selectOption("bitget");
  await page.getByLabel("ランキングの銘柄検索").fill("ETH");
  await page.getByLabel("売買代金の下限", { exact: true }).fill("1000000");
  await page.getByLabel("平常比下限", { exact: true }).fill("3");
  await page.getByLabel("当日位置の下限", { exact: true }).fill("25");
  await page.getByLabel("当日位置の上限", { exact: true }).fill("75");
  await page.getByLabel("順位外・未対応も表示").check();
  await page.getByRole("button", { name: "行順を固定", exact: true }).click();
  await movement.click();
  await expect(movement).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("15m");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("gainers");
  await expect(page.getByLabel("表示列プリセット")).toHaveValue("movement");
  await expect(page.getByLabel("取扱い取引所")).toHaveValue("bitget");
  await expect(page.getByLabel("ランキングの銘柄検索")).toHaveValue("");
  await expect(page.getByLabel("売買代金の下限", { exact: true })).toHaveValue("0");
  await expect(page.getByLabel("平常比下限", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("当日位置の下限", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("当日位置の上限", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("順位外・未対応も表示")).not.toBeChecked();
  await expect(page.getByRole("button", { name: "行順を固定", exact: true })).toBeVisible();
  await expect(btc.locator("button.select-row")).toHaveAttribute("aria-pressed", "true");

  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await expect(movement).toHaveAttribute("aria-pressed", "false");
  await activity.click();
  await expect(activity).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("15m");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await expect(page.getByLabel("表示列プリセット")).toHaveValue("movement");
  await expect(page.getByLabel("平常比下限", { exact: true })).toHaveValue("");
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "BTC");

  await favorites.click();
  await expect(favorites).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("お気に入りのみ", { exact: true })).toBeChecked();
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  await expect(page.getByTestId("ranking-row").first()).toHaveAttribute("data-asset", "BTC");
  await page.locator(".saved-view-management > summary").click();
  await page.getByLabel("表示名", { exact: true }).fill("監視リスト");
  await page.getByRole("button", { name: "表示条件を保存", exact: true }).click();
  await expect(page.getByLabel("保存した表示", { exact: true }).getByRole("option", { name: "監視リスト" })).toBeAttached();
  await whole.click();
  await page.getByLabel("保存した表示", { exact: true }).selectOption({ label: "監視リスト" });
  await expect(favorites).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  await whole.click();
  await expect(whole).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("24h");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await expect(page.getByLabel("表示列プリセット")).toHaveValue("standard");
  await expect(page.getByLabel("お気に入りのみ", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("取扱い取引所")).toHaveValue("bitget");
  await expect(chart).toHaveAttribute("data-symbol", "BYBIT:BTCUSDT.P");
  await expect(page.getByLabel("ランキングチャートの時間足")).toHaveValue("60");
  await expect(frame.locator(".tradingview-widget-container__widget")).toHaveText("BYBIT:BTCUSDT.P / 60");
  expect(await originalFrame!.evaluate(node => node.isConnected)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator(".ranking-conditions > summary").click();
  await page.locator(".saved-view-management > summary").click();
  await expect(page.locator(".ranking-conditions")).not.toHaveAttribute("open");
  await page.screenshot({ path: testInfo.outputPath("trader-reference-list.png") });
  if ((page.viewportSize()?.width ?? 1440) < 960) {
    await btc.locator("button.select-row").click();
    await expect(chart).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("trader-reference-detail.png") });
  }
  expect(errors).toEqual([]);
});
