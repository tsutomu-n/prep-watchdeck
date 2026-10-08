import { expect, test } from "@playwright/test";
import { attentionFixture } from "../../src/lib/attention/attention-test-fixture";
import type { UserWorkspace } from "../../src/lib/server/user-workspace-repository";

test("注目の成分・欠損・お気に入り・方向・停止時刻を独立して表示する", async ({ page }) => {
  const now = Date.parse("2026-10-09T00:31:15Z");
  await page.clock.install({ time: now });
  const fixture = attentionFixture(now);
  let stopped = false;
  let selectionWrites = 0;
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let workspace: UserWorkspace = { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] };
  await page.route("**/api/attention", route => route.fulfill(stopped ? { status: 503, json: { error: "stopped" } } : { json: fixture }));
  await page.route("**/api/selection**", route => { selectionWrites++; return route.abort(); });
  await page.route("https://**", route => route.abort());
  await page.route("**/api/user-workspace", async route => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON();
      workspace = { ...workspace, revision: workspace.revision + 1,
        favorites: body.enabled ? [...workspace.favorites, body.target] : workspace.favorites.filter(f => f.id !== body.target.id) };
    }
    await route.fulfill({ json: workspace });
  });
  await page.goto("/attention");
  await expect(page.getByRole("heading", { name: "市場の注目", exact: true })).toBeVisible();
  const eth = page.locator('tr[data-asset="ETH"]');
  await expect(eth).toContainText("4成分が揃っていません");
  await expect(eth).toContainText("基準 10/09 09:31:00 JST");
  await expect(eth.locator(".score")).toContainText("—");
  await page.getByRole("combobox", { name: "注目成分", exact: true }).selectOption("movement");
  await expect(eth).toContainText("↓ 下落");
  const star = page.getByRole("button", { name: "ETHをお気に入りに追加" });
  await star.focus();
  await expect(star).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "ETHをお気に入りから削除" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("お気に入り優先", { exact: true }).check();
  await expect(page.locator("tbody tr").first()).toHaveAttribute("data-asset", "ETH");
  await expect(eth.locator(".rank")).toHaveAttribute("aria-label", "市場順位 2");
  await expect(eth.getByRole("link", { name: "参照", exact: true })).toHaveAttribute("href", "/?mode=reference&selected=asset%3AETH");
  await expect(eth.getByRole("link", { name: "bitget", exact: true })).toHaveAttribute("href", "/?mode=native&instrument=bitget%3AETHUSDT&version=1");
  await page.getByLabel("銘柄検索", { exact: true }).fill("btc");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByLabel("銘柄検索", { exact: true }).fill("");
  const referenceTime = await page.locator(".update span").textContent();
  stopped = true;
  await page.clock.runFor(5100);
  await expect(page.getByRole("status")).toHaveText("更新停止");
  await expect(page.locator(".update span")).toHaveText(referenceTime!);
  await expect(page.locator("tbody tr")).toHaveCount(2);
  expect(selectionWrites).toBe(0);
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
