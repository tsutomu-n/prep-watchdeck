import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

test("売買代金の表示桁を保存して一覧と詳細に反映し、価格と計算条件は保つ", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
  }));
  const queries: URLSearchParams[] = [];
  await page.route("**/api/rankings?**", route => {
    const query = new URL(route.request().url()).searchParams;
    queries.push(query);
    const data = rankingFixture(query);
    const btc = data.rows.find(row => row.asset === "BTC")!;
    btc.quoteTurnover = 108129798.20669937;
    btc.referenceClose.value = 0.000123456789;
    btc.turnoverComparison.current.quoteTurnover = btc.quoteTurnover;
    btc.turnoverComparison.previousDay.quoteTurnover = 1250;
    btc.turnoverComparison.twoDaysAgo.quoteTurnover = 0.00000001;
    return route.fulfill({ json: data });
  });
  await page.goto("/settings");
  const setting = page.getByLabel("売買代金の表示小数桁", { exact: true });
  await expect(setting).toHaveValue("2");
  const nav = page.getByRole("navigation", { name: "メインメニュー" });
  for (const [digits, amount, compact, small] of [
    ["2", "108,129,798.21", "108.13M", "<0.01"],
    ["0", "108,129,798", "108M", "<1"],
    ["4", "108,129,798.2067", "108.1298M", "<0.0001"]
  ]) {
    await setting.selectOption(digits);
    await nav.getByRole("link", { name: "ランキング", exact: true }).click();
    const btc = page.locator('[data-testid="ranking-row"][data-asset="BTC"]');
    await expect(btc.locator(".turnover > span[title]")).toHaveText(compact);
    await expect(btc.locator(".turnover > span[title]")).toHaveAttribute("title", amount + " USDT");
    await expect(btc.getByTestId("relative-volume-signal")).toHaveAttribute("title", new RegExp(small));
    await btc.locator("button.select-row").click();
    const metrics = page.getByTestId("selected-primary-metrics").locator("dd");
    await expect(metrics.nth(0)).toHaveText("0.000123456789");
    await expect(metrics.nth(2)).toHaveText(amount);
    const amounts = page.getByTestId("relative-volume-details").locator(".day-windows dd");
    await expect(amounts).toHaveText([small, "1,250", amount]);
    await nav.getByRole("link", { name: "設定", exact: true }).click();
    await expect(setting).toHaveValue(digits);
  }
  await page.reload();
  await expect(setting).toHaveValue("4");
  expect(await page.evaluate(() => localStorage.getItem("prep-watchdeck:turnover-decimals"))).toBe("4");
  expect(queries.length).toBeGreaterThanOrEqual(3);
  expect(queries.map(query => [query.get("minTurnover"), query.get("order")]))
    .toEqual(queries.map(() => ["0", "turnover"]));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("turnover-display-settings.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test("保存不可でもタブ内の設定を維持し、保存失敗を表示する", async ({ page }) => {
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams)
  }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
  }));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new Error("storage denied"); } });
  });
  await page.goto("/settings");
  const setting = page.getByLabel("売買代金の表示小数桁", { exact: true });
  await setting.selectOption("0");
  await expect(page.getByRole("status").filter({ hasText: "保存できないため" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "メインメニュー" });
  await nav.getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await nav.getByRole("link", { name: "設定", exact: true }).click();
  await expect(setting).toHaveValue("0");
});
