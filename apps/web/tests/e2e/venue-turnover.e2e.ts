import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

for (const venue of ["bitget", "hyperliquid"] as const) {
const label = venue === "bitget" ? "Bitget" : "Hyperliquid";
const secondaryAsset = venue === "bitget" ? "ETH" : "HYPE";
const secondaryUnit = venue === "bitget" ? "USDT" : "USDC";
test(`${label}モードで24h売買代金をk/m表示し、更新・欠測を参照ランキングと分離する`, async ({ page }, testInfo) => {
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
    for (const row of data.rows) {
      if (row.asset === "ETH" && venue === "hyperliquid") {
        row.asset = secondaryAsset;
        row.id = `asset:${secondaryAsset}`;
        row.reference = { ...row.reference!, symbol: "HYPEUSDT", baseAsset: "HYPE" };
        row.widget.symbol = "BYBIT:HYPEUSDT.P";
      }
      const originalVenue = row.asset === "SOL" ? "aster" : venue;
      const symbol = originalVenue === "bitget" ? `${row.asset}USDT` : row.asset;
      row.venues = [originalVenue];
      row.originals = [{ ...row.originals[0], venue: originalVenue,
        instrumentId: `${originalVenue}:${symbol}`, symbol, baseAsset: row.asset }];
    }
    await route.fulfill({ json: data });
  });
  let volume = 850_000;
  let fail = false;
  let marketReads = 0;
  await page.route("**/api/market-data", async route => {
    marketReads++;
    if (fail) return route.fulfill({ status: 503, body: "unavailable" });
    const stamp = new Date(fixtureNow).toISOString();
    const items = ["BTC", secondaryAsset].map(asset => ({
      venue, venueInstrumentId: `${venue}:${asset}${venue === "bitget" ? "USDT" : ""}`, venueInstrumentVersionId: 1,
      sourceSymbol: venue === "bitget" ? `${asset}USDT` : asset, active: true, marketType: "linear_perpetual",
      quoteAsset: asset === secondaryAsset ? secondaryUnit : "USDT",
      quality: "ready", cycleAt: stamp, sourceAt: venue === "hyperliquid" ? null : stamp, observedAt: stamp,
      volume24hRaw: asset === "BTC" ? volume : 12_300_000, volume24hUnit: "quote"
    }));
    await route.fulfill({ json: { universe: { generatedAt: stamp, items } } });
  });
  await page.goto("/?mode=reference&period=1h&order=turnover");
  const modes = page.getByRole("group", { name: "ランキングの取引所モード" });
  const mode = modes.getByRole("button", { name: label, exact: true });
  const btc = page.getByTestId("ranking-row").filter({ has: page.locator("strong", { hasText: /^BTC$/ }) });
  const referenceValue = await btc.locator(".turnover > span[title]").innerText();
  await mode.click();
  await expect(mode).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByLabel("取扱い取引所")).toHaveValue(venue);
  await expect(page.getByTestId("ranking-row").filter({ hasText: "SOL" })).toHaveCount(0);
  await expect(btc.getByTestId(`${venue}-turnover`)).toContainText("850k USDT");
  await expect(page.locator(`[data-asset="${secondaryAsset}"]`).getByTestId(`${venue}-turnover`)).toContainText(`12.3m ${secondaryUnit}`);
  await expect(page.locator('[data-asset="NOCHART"]').getByTestId(`${venue}-turnover`)).toContainText("—");
  await expect(page.locator(`[data-asset="${secondaryAsset}"]`).getByTestId(`${venue}-turnover`)).toHaveAttribute("title", new RegExp(secondaryUnit));
  await expect(btc.locator(".turnover > span[title]")).toHaveText(referenceValue);
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("1h");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`${venue}-24h-turnover.png`) });
  volume = 1_250_000;
  fixtureNow += 15_000;
  await page.clock.fastForward(15_000);
  await expect(btc.getByTestId(`${venue}-turnover`)).toContainText("1.25m USDT");
  fail = true;
  fixtureNow += 15_000;
  await page.clock.fastForward(15_000);
  await expect(btc.getByTestId(`${venue}-turnover`)).toContainText("—");
  await expect(btc.locator(".turnover > span[title]")).toHaveText(referenceValue);
  await modes.getByRole("button", { name: "すべて", exact: true }).click();
  await expect(page.getByTestId(`${venue}-turnover`)).toHaveCount(0);
  const readsAfterExit = marketReads;
  fixtureNow += 30_000;
  await page.clock.fastForward(30_000);
  expect(marketReads).toBe(readsAfterExit);
  fail = false;
  await page.goto(`/rankings?venue=${venue}&period=1h&order=turnover`);
  await expect(mode).toHaveAttribute("aria-pressed", "true");
  await expect(btc.getByTestId(`${venue}-turnover`)).toContainText("1.25m USDT");
  expect(errors).toEqual([]);
});
}
