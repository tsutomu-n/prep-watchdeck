import { writeFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

test("元数量とChartが未確認でも参照ランキングを読み分けられる", async ({ page }, testInfo) => {
  await page.clock.install({ time: Date.parse("2026-09-16T10:31:15Z") });
  const widgetRequests: string[] = [];
  await page.route("https://s3.tradingview.com/**", route => {
    widgetRequests.push(route.request().url());
    return route.fulfill({ contentType: "application/javascript", body: "" });
  });
  await page.route("**/api/rankings?**", async route => {
    const now = await page.evaluate(() => Date.now());
    const data = rankingFixture(new URL(route.request().url()).searchParams, Math.floor(now / 60_000) * 60_000);
    const row = data.rows.find(item => item.asset === "BTC")!;
    row.originals[0].multiplier = null;
    row.widget = { status: "review", symbol: null, referenceKey: null,
      reason: "widget_not_reviewed", evidence: [] };
    data.coverage.widgetSupported -= 1;
    await route.fulfill({ json: data });
  });
  await page.goto("/rankings");
  const btc = page.getByTestId("ranking-row").filter({ hasText: "BTC" });
  await expect(btc.locator(".rank")).toContainText("1");
  await expect(btc).toContainText("+2.13%");
  await expect(btc.getByTestId("turnover-ratio")).toHaveText("平常比 2.0倍");
  await btc.getByRole("button").click();
  await expect(page.getByTestId("quantity-review")).toContainText("元の取引所の数量換算は未確認です");
  await expect(page.getByText("チャートの対応確認が必要です。", { exact: true })).toBeVisible();
  await expect(page.getByText("Chartの対応状況は、ランキングの数値計算には影響しません。", { exact: true })).toBeVisible();
  await page.getByText("元の取扱い契約と数量単位", { exact: true }).click();
  await expect(page.locator(".contracts")).toContainText("数量単位は要確認");
  await page.clock.fastForward(65_000);
  await expect(btc.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("quantity-review")).toBeVisible();
  expect(widgetRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("quantity-review-ranking.png"), fullPage: true });
});

test("順位変化と追加指標が同じ世代で切り替わり選択を維持する", async ({ page }, testInfo) => {
  await page.clock.install({ time: Date.parse("2026-09-12T00:31:15Z") });
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ contentType: "application/javascript", body: "" }));
  let phase = 0;
  let latest: ReturnType<typeof rankingFixture> | null = null;
  await page.route("**/api/rankings?**", async route => {
    const now = await page.evaluate(() => Date.now());
    const query = new URL(route.request().url()).searchParams;
    const data = rankingFixture(query, Math.floor(now / 60_000) * 60_000);
    if (phase) {
      data.previousGenerationId = `fixture:${data.cutoff - 60_000}`;
      data.previousCutoff = data.cutoff - 60_000;
      for (const row of data.rows) {
        row.rankChange = row.rank === null
          ? { status: "not_ranked", delta: null, previousRank: null, reason: row.state }
          : row.asset === "ETH"
            ? { status: "new", delta: null, previousRank: null, reason: "filtered" }
            : { status: "compared", delta: row.asset === "BTC" ? 5 : 0,
              previousRank: row.rank + (row.asset === "BTC" ? 5 : 0), reason: null };
      }
    }
    latest = data;
    await route.fulfill({ json: data });
  });
  await page.goto("/rankings");
  const btc = page.getByTestId("ranking-row").filter({ hasText: "BTC" });
  await expect(btc.getByTestId("rank-change")).toHaveText("比較不可（初回・再起動後）");
  await expect(btc.getByTestId("turnover-ratio")).toHaveText("平常比 2.0倍");
  await expect(btc.getByTestId("day-position")).toHaveText("当日位置 50.0%");
  await btc.getByRole("button").click();
  const selected = page.getByTestId("selected-metrics");
  await expect(selected).toContainText("2.0倍");
  await expect(selected).toContainText("50.0%");
  phase = 1;
  await page.clock.fastForward(65_000);
  await expect(btc.getByTestId("rank-change")).toHaveText("+5");
  await expect(selected).toContainText("+5");
  await expect(page.getByTestId("ranking-row").filter({ hasText: "ETH" }).getByTestId("rank-change")).toHaveText("新規");
  await expect(btc.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: testInfo.outputPath("daily-ranking.png"), fullPage: true });
  await writeFile(testInfo.outputPath("displayed-response.json"), JSON.stringify(latest, null, 2));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await expect(btc.getByTestId("turnover-ratio")).toHaveText("平常比 15分・1時間のみ");
  await expect(selected).toContainText("15分・1時間のみ");
  await expect(btc.getByTestId("day-position")).toHaveText("当日位置 50.0%");
  // Browser clock must invalidate the comparison even when the collector stops responding.
  await page.route("**/api/rankings?**", route => route.fulfill({ status: 503, body: "stopped" }));
  await page.clock.fastForward(160_000);
  await expect(btc.getByTestId("rank-change")).toHaveText("比較不可（古い結果）");
  await expect(page.getByText(/更新が停止しています。表示値は/)).toBeVisible();
});
