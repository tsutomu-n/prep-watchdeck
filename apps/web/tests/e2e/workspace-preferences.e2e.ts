import { expect, test, type Page } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

const savedViews = [{ id: "one-hour", name: "1時間の監視", view: {
  mode: "reference", period: "1h", order: "turnover", reference: "09:00", minimum: 0,
  preset: "movement", search: "", venue: "all", sort: "server", direction: "asc"
} }];
async function prepare(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews }
  }));
  await page.route("**/api/rankings?**", route => {
    const data = rankingFixture(new URL(route.request().url()).searchParams);
    const btc = data.rows.find(row => row.asset === "BTC")!;
    btc.returnPct = 1.234567;
    btc.referenceClose.value = 0.000123456789;
    btc.quoteTurnover = 1234567.8912;
    btc.turnoverComparison.previousDayRatio.value = 2.456789;
    btc.turnoverComparison.twoDaysAgoRatio.value = 2.456789;
    data.rows.push(...Array.from({ length: 30 }, (_, index) => ({ ...btc,
      id: `asset:EXTRA${index}`, asset: `EXTRA${index}`, rank: index + 10 })));
    return route.fulfill({ json: data });
  });
  return errors;
}
const nav = (page: Page) => page.getByRole("navigation", { name: "メインメニュー" });

test("超高密度は実際に一覧の行高と上部領域を縮め、設定と価格を保持する", async ({ page }, testInfo) => {
  const errors = await prepare(page);
  await page.goto("/");
  const row = page.getByTestId("ranking-row").filter({ has: page.locator("strong", { hasText: /^BTC$/ }) });
  await expect(row).toBeVisible();
  const normal = await row.boundingBox();
  await page.screenshot({ path: testInfo.outputPath("normal.png"), fullPage: true });
  await nav(page).getByRole("link", { name: "設定", exact: true }).click();
  await page.getByLabel("レイアウト", { exact: true }).selectOption("ultra");
  await page.getByLabel("騰落率・Fundingの小数桁", { exact: true }).selectOption("4");
  await page.getByLabel("比率の小数桁", { exact: true }).selectOption("3");
  await page.getByLabel("数量の小数桁", { exact: true }).selectOption("4");
  await page.getByLabel("一覧の売買代金", { exact: true }).selectOption("full");
  await page.getByLabel("売買代金の急増倍率", { exact: true }).fill("2");
  await page.getByLabel("売買代金の急増倍率", { exact: true }).blur();
  await page.getByLabel("上昇・下落の境界（%）", { exact: true }).fill("1");
  await page.getByLabel("上昇・下落の境界（%）", { exact: true }).blur();
  await page.reload();
  await expect(page.getByLabel("レイアウト", { exact: true })).toHaveValue("ultra");
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(row).toHaveAttribute("data-volume-surge", "up");
  await expect(row.locator(".change")).toContainText("+1.2346%");
  await expect(row.locator(".turnover > span[title]")).toHaveText("1,234,567.89");
  const ultra = await row.boundingBox();
  expect(ultra!.height).toBeLessThan(normal!.height);
  expect(ultra!.y).toBeLessThan(normal!.y);
  if ((page.viewportSize()?.width ?? 1440) > 960) expect(ultra!.height).toBeLessThanOrEqual(26);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("ultra.png"), fullPage: true });
  await row.locator("button.select-row").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("selected-primary-metrics").locator("dd").first()).toHaveText("0.000123456789");
  await expect(page.getByTestId("relative-volume-details").locator(".day-ratios")).toContainText("2.457倍");
  await nav(page).getByRole("link", { name: "設定", exact: true }).click();
  await page.getByLabel("文字サイズ", { exact: true }).selectOption("large");
  await page.getByLabel("一覧の行間", { exact: true }).selectOption("comfortable");
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(row).toBeVisible();
  expect((await row.boundingBox())!.height).toBeGreaterThan(ultra!.height);
  expect(await row.locator("button.select-row strong").evaluate(el => parseFloat(getComputedStyle(el).fontSize))).toBe(15);
  await writeFile(testInfo.outputPath("density.json"), JSON.stringify({ normal, ultra }, null, 2));
  await testInfo.attach("density.json", { body: JSON.stringify({ normal, ultra }), contentType: "application/json" });
  expect(errors).toEqual([]);
});

test("起動の初期条件・保存表示・URLを優先順どおり適用しチャートの初期足を選べる", async ({ page }) => {
  const errors = await prepare(page);
  await page.goto("/settings");
  await page.getByLabel("ランキングの初期比較期間", { exact: true }).selectOption("1h");
  await page.getByLabel("ランキングの初期並び順", { exact: true }).selectOption("losers");
  await page.getByLabel("ランキングの初期表示列", { exact: true }).selectOption("movement");
  await page.getByLabel("チャートの初期時間足", { exact: true }).selectOption("60");
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("1h");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("losers");
  await expect(page.getByLabel("表示列プリセット")).toHaveValue("movement");
  await page.goto("/?mode=reference&period=15m");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("15m");
  await page.goto("/?mode=reference&period=15m&order=turnover&dailyReferenceJst=00%3A00&minTurnover=0");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("15m");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await page.locator('[data-testid="ranking-row"][data-asset="BTC"] button.select-row').click();
  await expect(page.getByLabel("ランキングチャートの時間足")).toHaveValue("60");
  await page.goto("/settings");
  await page.getByLabel("ランキングで最初に使う保存表示").selectOption("one-hour");
  await expect(page.getByLabel("ランキングの初期比較期間")).toBeDisabled();
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByLabel("保存した表示", { exact: true })).toHaveValue("one-hour");
  await expect(page.getByLabel("ランキングの並び順")).toHaveValue("turnover");
  await page.goto("/?mode=reference&period=24h&order=gainers&dailyReferenceJst=00%3A00&minTurnover=0");
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("24h");
  await expect(page.getByLabel("保存した表示", { exact: true })).toHaveValue("");
  await page.goto("/settings");
  await page.getByLabel("最初に開く画面", { exact: true }).selectOption("native");
  await page.goto("/");
  await expect(nav(page).getByRole("link", { name: "取引所別", exact: true })).toHaveAttribute("aria-current", "page");
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByLabel("ランキングの比較期間")).toBeVisible();
  expect(errors).toEqual([]);
});

test("別タブに設定が反映され、保存不可でもタブ内で維持しリセットできる", async ({ page, context }) => {
  await prepare(page);
  await page.goto("/settings");
  const other = await context.newPage();
  await other.goto("/settings");
  await page.getByLabel("レイアウト", { exact: true }).selectOption("ultra");
  await expect(other.getByLabel("レイアウト", { exact: true })).toHaveValue("ultra");
  await page.getByRole("button", { name: "レイアウトと文字を初期値に戻す", exact: true }).click();
  await expect(other.getByLabel("レイアウト", { exact: true })).toHaveValue("normal");
  await other.close();
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new Error("denied"); } });
  });
  await page.reload();
  await page.getByLabel("レイアウト", { exact: true }).selectOption("ultra");
  await expect(page.getByRole("status").filter({ hasText: "保存できないため" })).toBeVisible();
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-layout", "ultra");
  await nav(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByLabel("レイアウト", { exact: true })).toHaveValue("ultra");
});

test("遅い初期保存表示は開始済みの操作を上書きせず、削除済みは案内する", async ({ page }) => {
  const errors = await prepare(page);
  await page.addInitScript(() => localStorage.setItem("prep-watchdeck:workspace-preferences:v1",
    JSON.stringify({ referenceViewId: "one-hour" })));
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/api/user-workspace", async route => {
    await held;
    await route.fulfill({ json: { schemaVersion: 1, revision: 0, favorites: [], savedViews } });
  });
  await page.goto("/?mode=reference");
  await page.getByLabel("ランキングの比較期間").selectOption("daily");
  release();
  await expect(page.getByLabel("保存した表示", { exact: true }).locator("option[value='one-hour']")).toBeAttached();
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("daily");
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
  }));
  await page.reload();
  await expect(page.getByText("初期表示に指定した保存表示が見つかりません。初期値を使っています。", { exact: true })).toBeVisible();
  await expect(page.getByLabel("ランキングの比較期間")).toHaveValue("24h");
  expect(errors).toEqual([]);
});


test("旧レイアウトをノーマルへ移行し、他の設定と新しい超高密度を保持する", async ({ page }) => {
  await prepare(page);
  await page.goto("/settings");
  for (const layout of ["standard", "ultra"]) {
    await page.evaluate(layout => {
      localStorage.removeItem("prep-watchdeck:workspace-preferences:v2");
      localStorage.setItem("prep-watchdeck:workspace-preferences:v1", JSON.stringify({
        layout, percentDecimals: 4, chartInterval: "60", chartVolume: false
      }));
    }, layout);
    await page.reload();
    await expect(page.getByLabel("レイアウト", { exact: true })).toHaveValue("normal");
    await expect(page.getByLabel("レイアウト", { exact: true }).locator("option")).toHaveText(["ノーマル", "超高密度"]);
    await expect(page.locator("html")).toHaveAttribute("data-layout", "normal");
    await expect(page.getByLabel("騰落率・Fundingの小数桁", { exact: true })).toHaveValue("4");
    await expect(page.getByLabel("チャートの初期時間足", { exact: true })).toHaveValue("60");
    await expect(page.getByLabel("取引所別チャートの出来高を表示", { exact: true })).not.toBeChecked();
  }
  await page.getByLabel("レイアウト", { exact: true }).selectOption("ultra");
  await page.reload();
  await expect(page.getByLabel("レイアウト", { exact: true })).toHaveValue("ultra");
});
