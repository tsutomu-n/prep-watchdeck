import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

async function surfaceChunk(name: "NativeMarkets" | "ReferenceMarkets") {
  const manifest = JSON.parse(await readFile(
    resolve(process.cwd(), ".svelte-kit/output/client/.vite/manifest.json"), "utf8"
  )) as Record<string, { file: string }>;
  const entry = Object.entries(manifest).find(([source]) => source.endsWith(`/${name}.svelte`));
  if (!entry) throw new Error(`${name} must be a separate production chunk`);
  return `/${entry[1].file}`;
}

const nav = (page: Page) => page.getByRole("navigation", { name: "メインメニュー" });

async function prepare(page: Page) {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", request => requests.push(new URL(request.url()).pathname));
  page.on("pageerror", error => errors.push(error.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/user-workspace", route => route.fulfill({
    json: { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] }
  }));
  await page.route("**/api/rankings?**", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams)
  }));
  await page.route("**/api/selection**", route => route.abort());
  await page.route("**/api/market-data**", route => route.abort());
  return { requests, errors };
}

test("ランキング表示は取引所別を読み込まず、メニューへのfocusはcodeだけ先読みする", async ({ page }) => {
  const nativeChunk = await surfaceChunk("NativeMarkets");
  const probe = await prepare(page);
  await page.goto("/?mode=reference");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  expect(probe.requests).not.toContain(nativeChunk);
  expect(probe.requests).not.toContain("/api/market-data");
  expect(probe.requests).not.toContain("/api/selection");

  const native = nav(page).getByRole("link", { name: "取引所別", exact: true });
  const prefetched = page.waitForResponse(response => new URL(response.url()).pathname === nativeChunk);
  const requestStart = probe.requests.length;
  await native.focus();
  expect((await prefetched).ok()).toBe(true);
  expect(probe.requests.slice(requestStart).filter(path =>
    path.startsWith("/api/") || path.endsWith("/__data.json"))).toEqual([]);
  await expect(page.locator(".universe-page")).toHaveCount(0);

  await native.click();
  await expect(page.locator(".universe-page")).toBeVisible();
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await expect(page.locator(".universe-page")).toHaveCount(0);
  expect(probe.errors).toEqual([]);
});

test("保存済みの取引所別を開く途中にランキングを起動せず、明示URLを優先する", async ({ page }) => {
  const referenceChunk = await surfaceChunk("ReferenceMarkets");
  const probe = await prepare(page);
  await page.addInitScript(() => localStorage.setItem("prep-watchdeck:workspace-preferences:v2",
    JSON.stringify({ initialPage: "native" })));
  await page.goto("/");
  await expect(page.locator(".universe-page")).toBeVisible();
  await expect(page).toHaveURL(/mode=native/);
  expect(probe.requests).not.toContain(referenceChunk);
  expect(probe.requests).not.toContain("/api/rankings");

  await page.goto("/?mode=reference");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await expect(page).toHaveURL(/mode=reference/);
  await page.goto("/rankings");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  await expect(page).toHaveURL(/\/rankings$/);
  expect(probe.errors).toEqual([]);
});

test("遅い画面codeの読み込み中に離れても古い画面とpollを起動しない", async ({ page }) => {
  const referenceChunk = await surfaceChunk("ReferenceMarkets");
  const probe = await prepare(page);
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let finish!: () => void;
  const finished = new Promise<void>(resolve => { finish = resolve; });
  await page.route(`**${referenceChunk}`, async route => {
    await held;
    await route.continue();
    finish();
  });
  await page.goto("/?mode=reference", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("status").filter({ hasText: "ランキングの画面を読み込んでいます。" })).toBeVisible();
  await nav(page).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
  release();
  await finished;
  await expect(page.locator(".ranking-page")).toHaveCount(0);
  expect(probe.requests).not.toContain("/api/rankings");
  await nav(page).getByRole("link", { name: "ランキング", exact: true }).click();
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
  expect(probe.errors).toEqual([]);
});

test("画面codeの取得失敗を表示し再読み込みで復帰できる", async ({ page }) => {
  const referenceChunk = await surfaceChunk("ReferenceMarkets");
  await prepare(page);
  await page.route(`**${referenceChunk}`, route => route.abort());
  await page.goto("/?mode=reference", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("alert")).toHaveText("画面を読み込めませんでした。通信状態を確認して再読み込みしてください。");
  await page.unroute(`**${referenceChunk}`);
  await page.getByRole("button", { name: "画面を再読み込み", exact: true }).click();
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
});
