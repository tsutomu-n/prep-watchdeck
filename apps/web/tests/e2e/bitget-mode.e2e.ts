import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

test("Bitgetモードで24h売買代金をk/m表示し、更新・欠測を参照ランキングと分離する", async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let fixtureNow = Date.parse("2026-10-08T03:00:15Z");
  await page.clock.install({ time: new Date(fixtureNow) });
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
  }));
  await page.route("**/api/rankings?**", async route => {
    const data = rankingFixture(new URL(route.request().url()).searchParams, Math.floor(fixtureNow / 60_000) * 60_000);
    for (const row of data.rows) row.venues = row.asset === "SOL" ? ["hyperliquid"] : ["bitget"];
    await route.fulfill({ json: data });
  });
  let volume = 850_000;
  let fail = false;
  let marketReads = 0;
  await page.route("**/api/market-data", async route => {
    marketReads++;
    if (fail) return route.fulfill({ status: 503, body: "unavailable" });
    const stamp = new Date(fixtureNow).toISOString();
    const items = ["BTC", "ETH"].map(asset => ({
      venue: "bitget", venueInstrumentId: `bitget:${asset}USDT`, venueInstrumentVersionId: 1,
      sourceSymbol: `${asset}USDT`, active: true, marketType: "linear_perpetual", quoteAsset: "USDT",
      quality: "ready", cycleAt: stamp, sourceAt: stamp, observedAt: stamp,
      volume24hRaw: asset === "BTC" ? volume : 12_300_000, volume24hUnit: "quote"
    }));
    await route.fulfill({ json: { universe: { generatedAt: stamp, items } } });
  });
  await page.goto("/?mode=reference&period=1h&order=turnover");
  const modes = page.getByRole("group", { name: "ランキングの取引所モード" });
  const bitget = modes.getByRole("button", { name: "Bitget", exact: true });
  const btc = page.getByTestId("ranking-row").filter({ has: page.locator("strong", { hasText: /^BTC$/ }) });
  const referenceValue = await btc.locator(".turnover > span[title]").innerText();
  await bitget.click();
  await expect(bitget).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("取扱い取引所")).toHaveValue("bitget");
  await expect(page.getByTestId("ranking-row").filter({ hasText: "SOL" })).toHaveCount(0);
  await expect(btc.getByTestId("bitget-turnover")).toContainText("850k USDT");
  await expect(page.locator('[data-asset="ETH"]').getByTestId("bitget-turnover")).toContainText("12.3m USDT");
  await expect(page.locator('[data-asset="NOCHART"]').getByTestId("bitget-turnover")).toContainText("—");
  await expect(btc.locator(".turnover > span[title]")).toHaveText(referenceValue);
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("1h");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("bitget-24h-turnover.png") });
  volume = 1_250_000;
  fixtureNow += 15_000;
  await page.clock.fastForward(15_000);
  await expect(btc.getByTestId("bitget-turnover")).toContainText("1.25m USDT");
  fail = true;
  fixtureNow += 15_000;
  await page.clock.fastForward(15_000);
  await expect(btc.getByTestId("bitget-turnover")).toContainText("—");
  await expect(btc.locator(".turnover > span[title]")).toHaveText(referenceValue);
  await modes.getByRole("button", { name: "すべて", exact: true }).click();
  await expect(page.getByTestId("bitget-turnover")).toHaveCount(0);
  const readsAfterExit = marketReads;
  fixtureNow += 30_000;
  await page.clock.fastForward(30_000);
  expect(marketReads).toBe(readsAfterExit);
  fail = false;
  await page.goto("/rankings?venue=bitget&period=1h&order=turnover");
  await expect(bitget).toHaveAttribute("aria-pressed", "true");
  await expect(btc.getByTestId("bitget-turnover")).toContainText("1.25m USDT");
  expect(errors).toEqual([]);
});
