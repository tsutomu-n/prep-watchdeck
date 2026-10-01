import { expect, test, type Page } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

async function prepare(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
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
  if ((page.viewportSize()?.width ?? 1440) < 960) {
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
    await expect(page.getByRole("button", { name: /^BTC(?:\s|$)/ })).toBeFocused();
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
  await page.goto("/settings");
  await page.getByLabel("騰落率の基準時刻（日本時間）").fill("08:45");
  await page.getByLabel("騰落率の基準時刻（日本時間）").blur();
  await expect(page.getByText(/保存できない/)).toBeVisible();
  await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "ランキング", exact: true }).click();
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  await expect(page.getByText(/JST 08:45/).first()).toBeVisible();
  expect(errors).toEqual([]);
});
