import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";
import { nativeActivityFixture } from "../../src/lib/market/native-activity-test-fixture";

for (const density of ["normal", "ultra"] as const) {
  test(`Bitget短時間の普段比と減速を密度${density}で区別し、Hyperliquidには追加しない`, async ({ page }, testInfo) => {
    let now = Date.parse("2026-10-08T06:00:15Z");
    await page.clock.install({ time: new Date(now) });
    await page.addInitScript(layout => localStorage.setItem("prep-watchdeck:workspace-preferences:v2", JSON.stringify({ layout })), density);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
    await page.route("**/api/user-workspace", route => route.fulfill({ json: {
      schemaVersion: 1, revision: 0, favorites: [], savedViews: []
    } }));
    await page.route("**/api/rankings?**", route => route.fulfill({ json:
      rankingFixture(new URL(route.request().url()).searchParams, Math.floor(now / 60_000) * 60_000)
    }));
    await page.route("**/api/market-data", route => {
      const stamp = new Date(now).toISOString();
      const items = ["BTC", "ETH"].map(asset => ({ venue: "bitget", sourceSymbol: `${asset}USDT`,
        venueInstrumentId: `bitget:${asset}USDT`, venueInstrumentVersionId: 1, active: true,
        marketType: "linear_perpetual", quoteAsset: "USDT", quality: "ready", observedAt: stamp,
        cycleAt: stamp, sourceAt: stamp, volume24hRaw: 12_300_000, volume24hUnit: "quote" }));
      return route.fulfill({ json: { universe: { generatedAt: stamp, items } } });
    });
    let fail = false;
    let reads = 0;
    await page.route("**/api/native-activity", route => {
      reads++;
      if (fail) return route.fulfill({ status: 503, body: "unavailable" });
      const data = nativeActivityFixture(now);
      const eth = structuredClone(data.rows[0]);
      eth.sourceSymbol = "ETHUSDT";
      eth.venueInstrumentId = "bitget:ETHUSDT";
      for (const window of Object.values(eth.windows)) {
        window.current.turnover.value = 80_000;
        window.current.priceChangePct.value = 1.2;
        window.relativeRatio.value = 1;
        window.previousChangePct.value = (80_000 / 300_000 - 1) * 100;
      }
      data.rows.push(eth);
      return route.fulfill({ json: data });
    });
    await page.goto("/?mode=reference&venue=bitget&period=1h&order=turnover");
    await expect(page.locator("html")).toHaveAttribute("data-layout", density);
    const rows = page.getByTestId("ranking-row");
    const btc = page.locator('[data-asset="BTC"]');
    const signal = btc.getByTestId("native-activity-signal");
    await expect(signal).toHaveAttribute("data-state", "available");
    await expect(signal).toContainText(/3(?:\.0)?×/);
    await expect(signal).toContainText(/20%/);
    await expect(signal.getByTestId("native-activity-price-direction")).toHaveAttribute("data-direction", "down");
    await expect(btc).toHaveAttribute("data-volume-surge", "down");
    const referenceValue = await btc.locator(".turnover > span[title]").innerText();
    await expect(page.locator('[data-asset="NOCHART"]').getByTestId("native-activity-signal")).toHaveAttribute("data-state", "unavailable");
    await page.getByRole("group", { name: "目的別の表示" }).getByRole("button", { name: "売買代金の増加", exact: true }).click();
    await expect(rows.first()).toHaveAttribute("data-asset", "BTC");
    await expect(page.getByLabel("適用中のランキング条件")).toContainText("Bitget 15分普段比");
    await expect(btc.locator(".turnover > span[title]")).toHaveText(referenceValue);
    await expect(btc.getByTestId("bitget-turnover")).toContainText("12.3m USDT");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator('[data-testid="native-activity-signal"] .previous').evaluateAll(elements =>
      elements.every(element => element.scrollWidth <= element.clientWidth &&
        element.getBoundingClientRect().height < parseFloat(getComputedStyle(element).lineHeight) * 1.5)
    )).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`bitget-activity-${density}.png`) });
    await signal.click();
    await expect(page.getByTestId("native-activity-details")).toBeVisible();
    await expect(page.getByTestId("native-activity-details")).toContainText("240K");
    if ((page.viewportSize()?.width ?? 1440) < 960) {
      await page.getByRole("button", { name: "一覧へ戻る", exact: true }).click();
    }
    fail = true;
    now += 15_000;
    await page.clock.fastForward(15_000);
    await expect(signal).toHaveAttribute("data-state", "unavailable");
    await expect(btc).toHaveAttribute("data-volume-surge", "");
    await expect(btc.getByTestId("bitget-turnover")).toContainText("12.3m USDT");
    await page.getByRole("group", { name: "ランキングの取引所モード" }).getByRole("button", { name: "Hyperliquid", exact: true }).click();
    await expect(page.getByTestId("native-activity-signal")).toHaveCount(0);
    const afterExit = reads;
    now += 30_000;
    await page.clock.fastForward(30_000);
    expect(reads).toBe(afterExit);
    expect(errors).toEqual([]);
  });
}
