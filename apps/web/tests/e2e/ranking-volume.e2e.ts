import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

test("同銘柄の過去日比較を文字なしのSVGで示し、両方向と横ばいの取引急増を選べる", async ({ page }, testInfo) => {
  await page.clock.install({ time: Date.parse("2026-10-05T04:15:15Z") });
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ contentType: "application/javascript", body: "" }));
  await page.route("**/api/rankings?**", async route => {
    const now = await page.evaluate(() => Date.now());
    await route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams,
      Math.floor(now / 60_000) * 60_000) });
  });
  await page.goto("/rankings");
  const spotlight = page.getByTestId("volume-spotlight");
  await expect(spotlight.getByTestId("relative-volume-signal")).toHaveCount(3);
  await expect(spotlight.locator('[data-state="down"]')).toContainText("SOL");
  await expect(spotlight.locator('[data-state="volume"]')).toContainText("NOCHART");
  const btc = page.getByTestId("ranking-row").filter({ hasText: "BTC" });
  const signal = btc.getByTestId("relative-volume-signal");
  await expect(btc).toHaveAttribute("data-volume-surge", "up");
  await expect(signal).toHaveText("");
  await expect(signal.locator("svg")).toHaveCount(2);
  await expect(signal).toHaveAttribute("data-new", "false");
  await signal.hover();
  await expect(signal).toHaveAttribute("title", /昨日比 4.0倍 \/ 一昨日比 4.8倍/);
  await signal.focus();
  await page.keyboard.press("Enter");
  const details = page.getByTestId("relative-volume-details");
  await expect(details).toBeVisible();
  await expect(details).toContainText("昨日比4.0倍");
  await expect(details).toContainText("一昨日比4.8倍");
  await expect(details.locator(".day-windows dd").nth(0)).toHaveText("104,166.66666666667");
  await expect(details.locator(".day-windows dd").nth(1)).toHaveText("125,000");
  await expect(details.locator(".day-windows dd").nth(2)).toHaveText("500,000");
  await page.screenshot({ path: testInfo.outputPath("relative-volume-details.png"), fullPage: true });
  const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  if (await back.isVisible()) await back.click();
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await expect(signal).toHaveAttribute("title", /10\/05 12:15〜10\/05 13:15 JST/);
  await page.getByLabel("ランキングの銘柄検索").fill("SOL");
  await expect(spotlight.getByTestId("relative-volume-signal")).toHaveCount(1);
  await expect(spotlight).toContainText("SOL");
  await spotlight.getByTestId("relative-volume-signal").click();
  await expect(details).toContainText("昨日比3.0倍");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("連続世代での新着だけを示し、履歴不足と鮮度切れで強調を止める", async ({ page }, testInfo) => {
  await page.clock.install({ time: Date.parse("2026-10-05T04:15:15Z") });
  let phase = 0;
  await page.route("**/api/rankings?**", async route => {
    if (phase === 3) return route.fulfill({ status: 503, body: "stopped" });
    const now = await page.evaluate(() => Date.now());
    const data = rankingFixture(new URL(route.request().url()).searchParams, Math.floor(now / 60_000) * 60_000);
    const btc = data.rows.find(row => row.asset === "BTC")!;
    if (phase === 0) {
      btc.turnoverComparison.previousDayRatio.value = 1;
      btc.turnoverComparison.previousDay.quoteTurnover = btc.quoteTurnover;
    } else {
      data.previousGenerationId = `fixture:${data.cutoff - 60_000}`;
      data.previousCutoff = data.cutoff - 60_000;
    }
    if (phase === 2) {
      btc.turnoverComparison.twoDaysAgo.status = "history_missing";
      btc.turnoverComparison.twoDaysAgo.quoteTurnover = null;
      btc.turnoverComparison.twoDaysAgoRatio = { status: "history_missing", value: null };
    }
    return route.fulfill({ json: data });
  });
  await page.goto("/rankings");
  const btc = page.getByTestId("ranking-row").filter({ hasText: "BTC" });
  const signal = btc.getByTestId("relative-volume-signal");
  await expect(signal).toHaveAttribute("data-state", "normal");
  await expect(signal).toHaveAttribute("data-new", "false");
  phase = 1;
  await page.clock.fastForward(65_000);
  await expect(signal).toHaveAttribute("data-state", "up");
  await expect(signal).toHaveAttribute("data-new", "true");
  await page.screenshot({ path: testInfo.outputPath("relative-volume-new.png"), fullPage: true });
  phase = 2;
  await page.clock.fastForward(60_000);
  await expect(signal).toHaveAttribute("data-state", "unavailable");
  await expect(signal).toHaveAttribute("title", /履歴不足/);
  await expect(btc).toHaveAttribute("data-volume-surge", "");
  await expect(signal).toHaveAttribute("data-new", "false");
  phase = 3;
  await page.clock.fastForward(160_000);
  await expect(page.getByTestId("volume-spotlight")).toHaveCount(0);
  await expect(signal).toHaveAttribute("title", /更新停止/);
  await expect(page.getByTestId("ranking-row").filter({ hasText: "NOCHART" })).toHaveAttribute("data-volume-surge", "");
});
