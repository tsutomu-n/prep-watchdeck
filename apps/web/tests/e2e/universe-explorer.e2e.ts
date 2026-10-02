import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import type { MarketMetricsArtifact } from "../../src/lib/generated/market-metrics";
import type { MarketChartArtifact, Timeframe } from "../../src/lib/generated/market-chart";
import type { SelectedMarketArtifact } from "../../src/lib/generated/selected-market";
import type { MarketServiceStateArtifact } from "../../src/lib/generated/service-state";
import type {
  UniverseInstrumentArtifact,
  UniverseSnapshotArtifact
} from "../../src/lib/generated/universe-snapshot";
import {
  REFERENCE_TIME_STORAGE_KEY,
  dailyBaselineAt,
  type DailyPriceChange
} from "../../src/lib/market/price-change";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";
import { browserIme, type BrowserImeEvent } from "./helpers/browser-ime";

const BTC_NATIVE_DETAIL = "/?mode=native&instrument=bitget%3ABTCUSDT&version=1";

async function showMarketList(page: Page) {
  const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  if (!await back.isVisible()) return false;
  await back.click();
  await expect(back).toBeHidden();
  return true;
}

async function clickNativeListButton(page: Page, name: string) {
  await showMarketList(page);
  const button = page.getByRole("button", { name, exact: true });
  if (name.endsWith("の保存足照合を表示")
    && await page.evaluate(() => matchMedia("(max-width: 48rem)").matches)) {
    await page.getByRole("button", { name: name.replace("の保存足照合を表示", "を詳細表示"), exact: true }).click();
    await openSection(page, "取得元・品質");
  } else {
    await button.click();
  }
}

async function openSection(page: Page, name: string) {
  const summary = page.locator("summary").filter({ hasText: name });
  if (!await summary.evaluate(node => (node.parentElement as HTMLDetailsElement).open)) {
    await summary.click();
  }
}

async function openSettings(page: Page) {
  await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page.getByRole("heading", { name: "設定", exact: true })).toBeVisible();
}

async function returnToNative(page: Page) {
  await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "取引所別", exact: true }).click();
  await expect(page.getByRole("heading", { name: "取引所別", exact: true })).toBeVisible();
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
}

async function changeReferenceInOtherPage(page: Page, value: string) {
  const settings = await page.context().newPage();
  try {
    await settings.goto("/settings");
    const input = settings.getByLabel("騰落率の基準時刻（日本時間）", { exact: true });
    await input.fill(value);
    await input.blur();
    await expect(input).toHaveValue(value);
  } finally {
    await settings.close();
  }
}

test("P02 慎重な確認担当は日本語下書きと参照条件・keyboard focusをnative往復後に復元する", async ({ page }, testInfo) => {
  const imeEvidence: { field: string; events: BrowserImeEvent[] }[] = [];
  let holdReturn = false;
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?*", async route => {
    if (holdReturn) await held;
    const payload = rankingFixture(new URL(route.request().url()).searchParams);
    const btc = payload.rows.find(row => row.asset === "BTC")!;
    btc.originals.push({ ...btc.originals[0], venue: "hyperliquid", instrumentId: "hyperliquid:BTC", versionId: 2, symbol: "BTC", multiplier: null });
    btc.originals.push({ ...btc.originals[0], instrumentId: "bitget:ETHUSDT", versionId: 999, symbol: "ETHUSDT" });
    const extra = payload.rows.find(row => row.asset === "ETH")!;
    payload.rows.push(...Array.from({ length: 30 }, (_, i) => ({
      ...extra, id: `asset:EXTRA${i}`, asset: `EXTRA${i}`, rank: i + 10
    })));
    await route.fulfill({ json: payload });
  });
  await page.goto("/");
  await page.getByLabel("ランキングの比較期間").selectOption("1h");
  await openSection(page, "ランキング条件");
  await page.getByLabel("平常比期間").selectOption("1h");
  await page.getByLabel("平常比下限").fill("0.5");
  await page.getByLabel("当日位置の下限", { exact: true }).fill("20");
  await page.getByLabel("当日位置の上限", { exact: true }).fill("80");
  await page.getByLabel("表示列プリセット").selectOption("movement");
  const selected = page.getByTestId("ranking-row").filter({ hasText: "BTC" }).locator("button.select-row");
  await selected.focus();
  await selected.press("Enter");
  const detailBack = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  if (await detailBack.isVisible()) await expect(detailBack).toBeFocused();
  else await expect(selected).toBeFocused();
  await expect(page.getByRole("link", { name: "Hyperliquid · BTC を確認" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Bitget · ETHUSDT を確認" })).toHaveCount(0);
  const noteSummary = page.getByText("この参照市場の観測メモ", { exact: true });
  await noteSummary.focus();
  await noteSummary.press("Enter");
  const reason = page.getByLabel("理由", { exact: true });
  const note = page.getByLabel("短い観測メモ");
  await reason.focus();
  const reasonIme = await browserIme(page, reason);
  try {
    await reasonIme.compose("りゅうどうせいかくにん");
    await reasonIme.compose("流動性確認");
    await reasonIme.commit("流動性確認");
    await expect(reason).toHaveValue("流動性確認");
    const events = await reasonIme.events();
    const eventPath = testInfo.outputPath("p02-reason-browser-ime.json");
    await writeFile(eventPath, JSON.stringify(events, null, 2));
    await testInfo.attach("p02-reason-browser-ime.json", { path: eventPath, contentType: "application/json" });
    expect(events.some(event => event.type === "compositionstart" && event.isTrusted)).toBe(true);
    expect(events.some(event => event.type === "input" && event.isTrusted && event.isComposing)).toBe(true);
    expect(events.some(event => event.type === "compositionend" && event.data === "流動性確認")).toBe(true);
    expect(events.filter(event => event.type !== "compositionend").every(event => event.isTrusted)).toBe(true);
    imeEvidence.push({ field: "reference reason", events });
  } finally { await reasonIme.close(); }
  await reason.press("Tab");
  await expect(note).toBeFocused();
  const noteIme = await browserIme(page, note);
  try {
    await noteIme.compose("さんしょうもととじこくをさいかくにん");
    await noteIme.compose("参照元と時刻を再確認");
    await noteIme.commit("参照元と時刻を再確認");
    await expect(note).toHaveValue("参照元と時刻を再確認");
    const events = await noteIme.events();
    const eventPath = testInfo.outputPath("p02-note-browser-ime.json");
    await writeFile(eventPath, JSON.stringify(events, null, 2));
    await testInfo.attach("p02-note-browser-ime.json", { path: eventPath, contentType: "application/json" });
    expect(events.some(event => event.type === "compositionend" && event.data === "参照元と時刻を再確認")).toBe(true);
    expect(events.filter(event => event.type !== "compositionend").every(event => event.isTrusted)).toBe(true);
    imeEvidence.push({ field: "reference note", events });
  } finally { await noteIme.close(); }
  await expect(page.getByLabel("保存先の取扱い契約")).toHaveValue("bitget:BTCUSDT");
  const mobile = await showMarketList(page);
  const scroller = page.locator(".ranking-list .table-scroll");
  await scroller.evaluate(el => { el.scrollTop = 180; el.scrollLeft = 40; });
  const scroll = await scroller.evaluate(el => ({ top: el.scrollTop, left: el.scrollLeft }));
  expect(scroll.top).toBeGreaterThan(0);
  await expect.poll(async () => {
    const href = await page.getByRole("link", { name: "Bitget · BTCUSDT を確認", includeHidden: true }).getAttribute("href");
    return Number(new URL(href!, page.url()).searchParams.get("returnListTop"));
  }).toBe(scroll.top);
  if (mobile) {
    await page.goForward();
    await expect(detailBack).toBeVisible();
  }
  const nativeLink = page.getByRole("link", { name: "Bitget · BTCUSDT を確認" });
  await nativeLink.focus();
  await nativeLink.press("Enter");
  await expect(page.getByRole("region", { name: "価格・出来高" })).toContainText("bitget:BTCUSDT");
  await expect(reason).toHaveValue("流動性確認");
  await expect(note).toHaveValue("参照元と時刻を再確認");
  await note.focus();
  await note.press("End");
  await page.keyboard.insertText("・取扱い確認");
  await expect(note).toHaveValue("参照元と時刻を再確認・取扱い確認");
  holdReturn = true;
  const returnLink = page.getByRole("link", { name: "ランキングへ戻る" });
  await returnLink.focus();
  await returnLink.press("Enter");
  try {
    await openSection(page, "ランキング条件");
    await expect(page.getByLabel("平常比期間")).toHaveValue("1h");
    await expect(page.getByLabel("平常比下限")).toHaveValue("0.5");
    await expect(page.getByLabel("当日位置の下限", { exact: true })).toHaveValue("20");
    await expect(page.getByLabel("当日位置の上限", { exact: true })).toHaveValue("80");
    await expect(page.getByLabel("表示列プリセット")).toHaveValue("movement");
  } finally { release(); }
  await expect(selected).toHaveAttribute("aria-pressed", "true");
  await expect(selected).toBeFocused();
  await expect.poll(() => scroller.evaluate(el => ({ top: el.scrollTop, left: el.scrollLeft }))).toEqual(scroll);
  if (mobile) {
    await selected.press("Enter");
    await expect(detailBack).toBeFocused();
  }
  const next = page.getByRole("button", { name: "次の銘柄", exact: true });
  await next.focus();
  await next.press("Enter");
  await expect(page.getByRole("heading", { name: "NOCHART", exact: true })).toBeVisible();
  const previous = page.getByRole("button", { name: "前の銘柄", exact: true });
  await previous.focus();
  await previous.press("Enter");
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await noteSummary.focus();
  await noteSummary.press("Enter");
  await expect(reason).toHaveValue("流動性確認");
  await expect(note).toHaveValue("参照元と時刻を再確認・取扱い確認");
  await expect(page.getByLabel("保存先の取扱い契約")).toHaveValue("bitget:BTCUSDT");
  await note.focus();
  await note.press("Tab");
  const attachContext = page.getByLabel("保存時の指標を添付する");
  await expect(attachContext).toBeFocused();
  await attachContext.press("Space");
  await expect(attachContext).toBeChecked();
  await attachContext.press("Tab");
  const save = page.getByRole("button", { name: "注記を保存", exact: true });
  await expect(save).toBeFocused();
  await expect(save).toBeEnabled();
  await save.press("Enter");
  await expect(page.locator(".note-list")).toContainText("参照元と時刻を再確認・取扱い確認");
  const saved = await (await page.request.get("/api/market-past-notes?venueInstrumentId=bitget:BTCUSDT")).json();
  expect(saved.notes[0]).toMatchObject({
    venueInstrumentId: "bitget:BTCUSDT", reason: "流動性確認",
    note: "参照元と時刻を再確認・取扱い確認",
    context: { view: "reference", venueInstrumentVersionId: 1, reference: { source: "bybit", symbol: "BTCUSDT", period: "1h" } }
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const evidencePath = testInfo.outputPath("p02-browser-ime.json");
  await writeFile(evidencePath, JSON.stringify({ persona: "P02 慎重な確認担当", boundary: "Chromium CDP composition; OS IME and physical device unverified", viewport: page.viewportSize(), imeEvidence, saved: saved.notes[0] }, null, 2));
  await testInfo.attach("p02-browser-ime.json", { path: evidencePath, contentType: "application/json" });
  const screenshotPath = testInfo.outputPath("p02-reference-note.png");
  await page.screenshot({ path: screenshotPath });
  await testInfo.attach("p02-reference-note.png", { path: screenshotPath, contentType: "image/png" });
});

test("取引所別のお気に入りと名前付き表示を再読込後に使える", async ({ page }) => {
  await page.goto("/?mode=native");
  const favorite = page.getByRole("button", { name: "BTC bitgetをお気に入り登録" });
  await favorite.click();
  await expect(page.getByRole("button", { name: "BTC bitgetをお気に入り解除" }))
    .toHaveAttribute("aria-pressed", "true");
  await openSection(page, "表示条件を保存／管理");
  await page.getByLabel("取引所別の表示名").fill("BTC確認");
  await page.getByRole("button", { name: "表示条件を保存" }).click();
  await expect(page.getByLabel("取引所別の保存した表示").locator("option"))
    .toContainText(["選択してください", "BTC確認"]);
  await page.reload();
  await expect(page.getByRole("button", { name: "BTC bitgetをお気に入り解除" }))
    .toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("取引所別の保存した表示").selectOption({ label: "BTC確認" });
  await openSection(page, "表示条件を保存／管理");
  await expect(page.getByLabel("取引所別の表示名")).toHaveValue("BTC確認");
});

test("追加指標は現行IDとversionが一致する時だけ表示する", async ({ page }) => {
  const universe = JSON.parse(await readFile(resolve(artifactRoot, "universe-snapshot.json"), "utf-8")) as UniverseSnapshotArtifact;
  const instrument = universe.items.find((item) => item.venueInstrumentId === "bitget:BTCUSDT")!;
  const now = Date.now();
  const cutoff = new Date(Math.floor(now / 60_000) * 60_000 - 180_000).toISOString();
  const observed = new Date(now - 5_000).toISOString();
  const metric = (value: number, endAt: string) => ({
    value, availability: "available", reasonCode: null,
    startAt: endAt, endAt, startValue: 100, endValue: 110,
    endSourceAt: endAt, endObservedAt: observed, endFinality: "confirmed", unit: "base"
  });
  let version = instrument.venueInstrumentVersionId + 1;
  await page.route("**/api/market-metrics", (route) => route.fulfill({ json: {
    schemaVersion: 1, metricVersion: "native-endpoints-v1", generationId: "fixture-1",
    generatedAt: new Date().toISOString(), candleCutoff: cutoff,
    timingPolicy: { candleLagSeconds: 180, candleMaxAgeSeconds: 300 },
    rows: [{ venueInstrumentId: instrument.venueInstrumentId, venueInstrumentVersionId: version,
      venue: instrument.venue, sourceSymbol: instrument.sourceSymbol,
      quoteAsset: instrument.quoteAsset, settleAsset: instrument.settleAsset, priceTick: null,
      oiChange: { "15m": metric(10, observed), "1h": metric(20, observed) },
      tradeChange: { "15m": metric(5, cutoff), "1h": metric(6, cutoff), "24h": metric(7, cutoff) }
    }]
  } }));
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await expect(page.getByRole("region", { name: "追加の市場変化指標" })).toContainText("追加指標は準備中です");
  version = instrument.venueInstrumentVersionId;
  await expect(page.getByRole("region", { name: "追加の市場変化指標" })).toContainText("数量OI: 15m +10.00%", { timeout: 10_000 });
});

test("groupのないactive契約も単体チャートとJST変化を表示する", async ({ page }) => {
  const path = resolve(artifactRoot, "universe-snapshot.json");
  const universe = JSON.parse(await readFile(path, "utf-8")) as UniverseSnapshotArtifact;
  const item = universe.items.find((entry) => entry.venueInstrumentId === "bitget:BTCUSDT")!;
  item.groupId = null;
  await writeFile(path, JSON.stringify(universe));
  await page.goto(`/?mode=native&instrument=${encodeURIComponent(item.venueInstrumentId)}&version=${item.venueInstrumentVersionId}`);
  await expect(page.getByRole("region", { name: "価格・出来高" })).toBeVisible();
  await openSection(page, "選択データの監視状態");
  await expect(page.getByText("板・約定購読は行いません。")).toBeVisible();
  await expect(page.getByRole("heading", { name: "約定価格の騰落率" })).toBeVisible();
  await expect(page.locator(".daily-change-block")).not.toContainText("group未確定");
});

const runtimeRoot = resolve(process.cwd(), "../../var/tmp/e2e/runtime");
const artifactRoot = resolve(runtimeRoot, "artifacts");
const selectionPath = resolve(runtimeRoot, "control", "selection.json");
const pageErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
  const now = new Date();
  await rm(selectionPath, { force: true });
  await rm(`${selectionPath}.lock`, { force: true });
  await publishArtifacts(now);
  await page.route("**/api/chart-history?*", (route) => route.fulfill({
    json: chartHistoryFixture(new URL(route.request().url()), now)
  }));
  await page.route("**/api/price-change?*", async (route) => route.fulfill({
    json: priceChangeFixture(new URL(route.request().url()), await browserNow(page))
  }));
});

test.afterEach(async ({ page }) => {
  // Stop timers and requests before removing the isolated state. A request already
  // admitted by the preview server can briefly retain its repository lock.
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.close();
  await rm(runtimeRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  expect(pageErrors.get(page) ?? [], "ブラウザの未処理例外").toEqual([]);
});

test("一覧選択した取引所契約を再読込しても同じ詳細へ戻れる", async ({ page }, testInfo) => {
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toContainText("bitget:ETHUSDT");
  await page.reload();
  await expect(chart).toContainText("bitget:ETHUSDT");
  expect(new URL(page.url()).searchParams.get("instrument")).toBe("bitget:ETHUSDT");
  expect(new URL(page.url()).searchParams.get("version")).toBe("3");
  if (testInfo.project.name === "mobile-390") {
    const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
    await expect(back).toBeVisible();
    await back.click();
    await expect(back).toBeHidden();
    await expect(page.getByRole("button", { name: "ETH bitgetを詳細表示", exact: true })).toBeVisible();
  }
});

test("一覧選択した参照銘柄を再読込しても同じ詳細へ戻れる", async ({ page }, testInfo) => {
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?*", route => route.fulfill({
    json: rankingFixture(new URL(route.request().url()).searchParams)
  }));
  await page.goto("/");
  await page.getByTestId("ranking-row").filter({ hasText: "BTC" }).locator("button.select-row").click();
  const selected = page.getByRole("heading", { name: "BTC", exact: true });
  await expect(selected).toBeVisible();
  await page.reload();
  await expect(selected).toBeVisible();
  expect(new URL(page.url()).searchParams.get("selected")).toBe("asset:BTC");
  if (testInfo.project.name === "mobile-390") {
    const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
    await expect(back).toBeVisible();
    await back.click();
    await expect(back).toBeHidden();
    await expect(page.getByTestId("ranking-row").filter({ hasText: "BTC" })).toBeVisible();
  }
});

test("Universe Explorerの主要flowを操作できる", async ({ page }, testInfo) => {
  await page.goto("/?mode=native");

  await expect(page.getByRole("heading", { name: "取引所別" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "銘柄一覧" })).toBeVisible();
  await expect(page.getByLabel("運用上の注意")).toBeVisible();
  await expect(page.getByLabel("データ品質理由")).toBeVisible();

  const search = page.getByLabel("検索", { exact: true });
  await search.fill("ETH");
  await expect(page.getByRole("button", { name: "ETH bitgetを詳細表示" })).toBeVisible();
  await expect(page.getByRole("button", { name: "BTC bitgetを詳細表示" })).toHaveCount(0);
  await search.clear();

  await clickNativeListButton(page, "BTC hyperliquidを詳細表示");
  const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  const mobile = await back.isVisible();
  if (mobile) {
    await expect(page.getByRole("heading", { name: "銘柄一覧" })).toBeHidden();
    await expect(page.locator("#inspector-title")).toBeFocused();
  }
  await expect(page.getByLabel("選択契約のデータ元")).toContainText("Hyperliquidの公開データ");
  await expect(page.getByLabel("選択契約の主要指標")).toContainText("JST 00:00基準");
  await expect(page.getByLabel("選択契約の主要指標")).toContainText("直近15分の変化");
  await expect(page.locator(".inspector .l1-block")).not.toHaveAttribute("open");
  await page.screenshot({ path: testInfo.outputPath("trader-native-detail.png") });
  await openSection(page, "選択データの監視状態");
  await expect(page.getByText("詳細データを要求しました", { exact: true })).toBeVisible();
  await expect
    .poll(async () => (await readSelectionCommand())?.venueInstrumentId ?? null)
    .toBe("hyperliquid:BTC");

  const command = await readSelectionCommand();
  expect(command).toMatchObject({
    groupId: "crypto:BTC:linear-perp",
    venueInstrumentId: "hyperliquid:BTC"
  });
  await expect(
    page.getByRole("region", { name: "選択groupの板・約定" }).getByText(/artifactを待っています/)
  ).toBeVisible();

  await rm(resolve(artifactRoot, "service-state.json"), { force: true });
  await expect(page.getByText("更新停止", { exact: true })).toBeVisible({ timeout: 8_000 });
  await showMarketList(page);
  if (mobile) await expect(page.getByRole("button", { name: "BTC hyperliquidを詳細表示", exact: true })).toBeFocused();
  await expect(page.getByRole("heading", { name: "銘柄一覧" })).toBeVisible();

  const horizontalOverflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
});

test("監査CLIの不変ファイルをAPIと取得元・品質画面で読める", async ({ page, request }) => {
  const absent = await request.get("/api/candle-audits");
  expect(absent.status()).toBe(200);
  expect((await absent.json()).state).toBe("not_run");
  const nonlocal = await request.get("/api/candle-audits", {
    headers: { host: "outside.invalid" }
  });
  expect(nonlocal.status()).toBe(403);
  const runId = await publishSyntheticAuditForBitget();
  const indexResponse = await request.get("/api/candle-audits");
  expect(indexResponse.status()).toBe(200);
  expect(indexResponse.headers()["cache-control"]).toBe("no-store");
  const index = await indexResponse.json();
  expect(index.state).toBe("available");
  expect(index.index.entries[0].runId).toBe(runId);
  const detailResponse = await request.get(`/api/candle-audits/${runId}?offset=0&limit=2`);
  expect(detailResponse.status()).toBe(200);
  const detail = await detailResponse.json();
  expect(detail.report.outcome).toBe("differences");
  expect(detail.totalFindings).toBeGreaterThan(0);
  expect(detail.findings).toHaveLength(2);
  expect(detail.markerBuckets.length).toBeGreaterThan(0);
  expect((await request.get(`/api/candle-audits/${runId}?offset=-1`)).status()).toBe(400);
  expect((await request.get("/api/candle-audits/invalid-run")).status()).toBe(400);
  expect((await request.get(`/api/candle-audits/${"0".repeat(32)}`)).status()).toBe(404);

  await page.goto("/?mode=native");
  await expect(page.getByRole("button", { name: "BTC bitgetの保存足照合を表示", includeHidden: true }))
    .toContainText("差異あり");
  await clickNativeListButton(page, "BTC bitgetの保存足照合を表示");
  await expect(page.getByRole("heading", { name: "保存足照合" })).toBeVisible();
  await expect(page.getByText("価格差異", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("テストデータ", { exact: false }).first()).toBeVisible();
  const toggle = page.getByRole("checkbox", { name: "保存データの照合箇所を表示" });
  await expect(toggle).not.toBeChecked();
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 120本/);
  const visibleBefore = await chart.getByLabel("チャート表示期間").textContent();
  await toggle.check();
  await expect(toggle).toBeChecked();
  await expect(chart.getByRole("status").filter({ hasText: "保存足照合の印" }))
    .toContainText(/読み込んだ足で[1-9]\d*か所/);
  await expect(chart.getByLabel("チャート表示期間")).toHaveText(visibleBefore ?? "");
  await page.getByRole("button", { name: "同時刻を見る" }).first().click();
  await expect(page.getByRole("status").filter({ hasText: /対応する表示足/ })).toBeVisible();
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await expect(page.getByRole("checkbox", { name: "保存データの照合箇所を表示" })).toHaveCount(0);
  const overflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(overflow).toBeLessThanOrEqual(1);
  await writeFile(resolve(artifactRoot, "candle-audit-index.json"), '{"schemaVersion":99}');
  const broken = await request.get("/api/candle-audits");
  expect(broken.status()).toBe(503);
  expect(await broken.text()).not.toMatch(/\/home\/|password|stack/i);
  await writeFile(resolve(artifactRoot, "candle-recovery-state.json"), "x".repeat(1024 * 1024 + 1));
  const oversized = await request.get("/api/candle-recovery");
  expect(oversized.status()).toBe(503);
  expect(await oversized.text()).not.toMatch(/\/home\/|password|stack/i);
});

test("監査詳細の全ページで51時刻のmarker要約を保つ", async ({ request }) => {
  const runId = await publishSyntheticAuditForBitget(51, true);
  const ids: string[] = [];
  let offset = 0;
  let total = 0;
  for (let pageNumber = 0; pageNumber < 20; pageNumber++) {
    const response = await request.get(`/api/candle-audits/${runId}?offset=${offset}&limit=20`);
    expect(response.status()).toBe(200);
    const detail = await response.json();
    total = detail.totalFindings;
    expect(detail.markerBuckets).toHaveLength(51);
    expect(detail.markerBuckets[0].bucketAt).toBeDefined();
    ids.push(...detail.findings.map((finding: { id: string }) => finding.id));
    offset += detail.findings.length;
    if (!detail.hasMore) break;
  }
  expect(ids.length).toBe(total);
  expect(new Set(ids).size).toBe(total);
});

test("監査の新run到着後も閲覧中のrunを保ち、明示切替する", async ({ page }) => {
  await page.clock.install();
  const first = await publishSyntheticAuditForBitget();
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "BTC bitgetの保存足照合を表示");
  await expect(page.getByRole("heading", { name: "保存足照合" })).toBeVisible();
  await page.locator(".source-quality .technical > summary").click();
  await expect(page.locator(".source-quality .technical")).toContainText(first);
  const second = await publishSyntheticAuditForBitget();
  expect(second).not.toBe(first);
  await page.clock.fastForward(60_001);
  const switchRun = page.getByRole("button", { name: "新しい照合記録を見る" });
  await expect(switchRun).toBeVisible();
  await expect(page.locator(".source-quality .technical")).toContainText(first);
  await switchRun.click();
  await expect(page.locator(".source-quality .technical")).toContainText(second);
});

test("監査詳細の遅い旧応答はA→B→A後の表示を変えない", async ({ page }) => {
  const runId = await publishSyntheticAuditForBitget();
  let release!: (route: Route) => void;
  const firstRoute = new Promise<Route>((resolveRoute) => { release = resolveRoute; });
  let captured = false;
  await page.route(`**/api/candle-audits/${runId}?*`, async (route) => {
    if (!captured) {
      captured = true;
      release(route);
      return;
    }
    await route.fallback();
  });
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "BTC bitgetの保存足照合を表示");
  const held = await firstRoute;
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await clickNativeListButton(page, "BTC bitgetの保存足照合を表示");
  await expect(page.getByText("価格差異", { exact: false }).first()).toBeVisible();
  const current = await (await page.request.get(`/api/candle-audits/${runId}`)).json();
  await held.fulfill({ json: { ...current, totalFindings: 0, findings: [], markerBuckets: [] } })
    .catch(() => undefined);
  await settleChartPaint(page);
  await expect(page.getByText("価格差異", { exact: false }).first()).toBeVisible();
  await expect(page.getByText(/照合箇所 [1-9]\d*件/)).toBeVisible();
});

test("Recoveryの実HTTP・隔離DB・状態ファイルをAPIから画面まで通す", async ({ page, request }) => {
  test.skip(!process.env.TEST_DATABASE_URL, "隔離TEST_DATABASE_URLが必要");
  const result = await new Promise<{ code: number | null; stdout: string; stderr: string }>((resolveResult, reject) => {
    const child = spawn("uv", ["run", "--no-sync", "python", "-m",
      "tests.recovery_browser_probe", runtimeRoot], {
      cwd: resolve(process.cwd(), "../market-core"), stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (part: Buffer) => { stdout += part.toString(); });
    child.stderr.on("data", (part: Buffer) => { stderr += part.toString(); });
    child.on("error", reject);
    child.on("close", (code) => resolveResult({ code, stdout, stderr }));
  });
  expect(result.code, result.stderr).toBe(0);
  const produced = JSON.parse(result.stdout) as { runId: string; missingBefore: number;
    inserted: number; remaining: number };
  expect(produced).toMatchObject({ missingBefore: 1, inserted: 1, remaining: 0 });
  const response = await request.get("/api/candle-recovery");
  expect(response.status()).toBe(200);
  const published = await response.json();
  expect(published.state).toBe("available");
  expect(published.recovery.runId).toBe(produced.runId);
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "BTC bitgetの保存足照合を表示");
  await expect(page.getByRole("heading", { name: "保存足の回収" })).toBeVisible();
  await expect(page.getByText(/この契約: 欠損 1 → 0、挿入 1/)).toBeVisible();
  await expect(page.getByText(/全市場: 対象 1\/1、欠損 1 → 0、挿入 1/)).toBeVisible();
});

test("約定騰落率の基準を分単位で変更して再読み込み後も保持する", async ({ page }, testInfo) => {
  await page.goto(BTC_NATIVE_DETAIL);
  const setting = page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true });
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  const row = page.getByRole("row").filter({
    has: page.getByRole("button", { name: "BTC bitgetを詳細表示", exact: true })
  });
  await expect(change).toContainText("JST 00:00基準");
  await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
  await expect(change.getByText("103", { exact: true })).toBeVisible();
  await expect(change.getByText("100", { exact: true })).toBeVisible();
  await showMarketList(page);
  await expect(row.getByRole("cell", { name: /\+3\.00%/ })).toBeVisible();
  await expect(row.getByRole("cell", { name: /65,000/ })).toBeVisible();
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await openSettings(page);
  await expect(setting).toHaveValue("00:00");

  const changed = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/price-change"
      && url.searchParams.get("instrument") === "bitget:BTCUSDT"
      && url.searchParams.get("referenceTime") === "09:07";
  });
  await setting.fill("09:07");
  await setting.blur();
  await returnToNative(page);
  await (await changed).finished();
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  await showMarketList(page);
  await expect(row.getByRole("cell", { name: /-6\.36%/ })).toBeVisible();
  expect(await page.evaluate((key) => localStorage.getItem(key), REFERENCE_TIME_STORAGE_KEY))
    .toBe("09:07");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");

  await page.reload();
  await openSettings(page);
  await expect(setting).toHaveValue("09:07");
  await returnToNative(page);
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  const horizontalOverflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
  await testInfo.attach("daily-change-layout", {
    body: JSON.stringify({ viewport: page.viewportSize(), horizontalOverflow }),
    contentType: "application/json"
  });
  await page.screenshot({ path: testInfo.outputPath("daily-change-page.png"), fullPage: true });
  await change.screenshot({ path: testInfo.outputPath("daily-change-detail.png") });
});

test("約定騰落率の古い基準の遅延応答で変更後の値を上書きしない", async ({ page }) => {
  let receiveDelayedRoute: (route: Route) => void = () => undefined;
  const delayedRoute = new Promise<Route>((resolve) => { receiveDelayedRoute = resolve; });
  await page.route("**/api/price-change?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("instrument") === "bitget:BTCUSDT"
      && url.searchParams.get("referenceTime") === "00:00") {
      receiveDelayedRoute(route);
      return;
    }
    await route.fallback();
  });
  await page.goto(BTC_NATIVE_DETAIL);
  const pending = await delayedRoute;
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(change).toContainText("取得中");
  await changeReferenceInOtherPage(page, "09:07");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();

  await pending.fulfill({
    json: priceChangeFixture(new URL(pending.request().url()), await browserNow(page))
  });
  await settleChartPaint(page);
  await expect(change).toContainText("JST 09:07基準");
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
  await expect(change.getByText("+3.00%", { exact: true })).toHaveCount(0);
});

test.describe("約定騰落率のJST日付切替", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("日本時間の0時で旧基準の値を消して新しい基準を取得する", async ({ page }) => {
    const start = new Date("2026-09-10T14:59:50.000Z");
    const midnight = Date.parse("2026-09-10T15:00:00.000Z");
    await page.clock.install({ time: start });
    let receiveRolloverRoute: (route: Route) => void = () => undefined;
    const rolloverRoute = new Promise<Route>((resolve) => { receiveRolloverRoute = resolve; });
    await page.route("**/api/price-change?*", async (route) => {
      const url = new URL(route.request().url());
      const now = await browserNow(page);
      if (url.searchParams.get("instrument") === "bitget:BTCUSDT"
        && now.getTime() >= midnight) {
        receiveRolloverRoute(route);
        return;
      }
      await route.fulfill({ json: priceChangeFixture(url, now) });
    });
    await page.goto(BTC_NATIVE_DETAIL);
    const change = page.getByRole("region", { name: "約定価格の騰落率" });
    await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => Intl.DateTimeFormat().resolvedOptions().timeZone))
      .toBe("America/Los_Angeles");

    await page.clock.fastForward(11_000);
    const pending = await rolloverRoute;
    const url = new URL(pending.request().url());
    expect(url.searchParams.get("referenceTime")).toBe("00:00");
    await expect(change.getByText("+3.00%", { exact: true })).toHaveCount(0);
    await expect(change).toContainText("取得中");
    const fixture = priceChangeFixture(url, await browserNow(page), 102);
    expect(fixture.baselineAt).toBe("2026-09-10T15:00:00.000Z");
    await pending.fulfill({ json: fixture });
    await expect(change.getByText("+0.98%", { exact: true })).toBeVisible();
    await expect(change.getByText("102", { exact: true })).toBeVisible();
  });
});

test("約定騰落率の基準足欠損と取得失敗を0%に置き換えない", async ({ page }) => {
  await page.route("**/api/price-change?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("referenceTime") === "09:07") {
      await route.fulfill({ status: 503, json: { error: "fixture_unavailable" } });
      return;
    }
    const fixture = priceChangeFixture(url, await browserNow(page));
    await route.fulfill({ json: {
      ...fixture,
      status: "unavailable",
      reason: "baseline_missing",
      baselinePrice: null,
      changePercent: null
    } satisfies DailyPriceChange });
  });
  await page.goto(BTC_NATIVE_DETAIL);
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(change).toContainText("基準足なし");
  await expect(change.getByText(/^[+-]?\d[\d,.]*%$/)).toHaveCount(0);

  await changeReferenceInOtherPage(page, "09:07");
  await expect(change).toContainText("値動きの取得に失敗しました (503)");
  await expect(change.getByText(/^[+-]?\d[\d,.]*%$/)).toHaveCount(0);
  await expect(change).not.toContainText("基準足なし");
});

test("約定騰落率の設定はstorageが使えなくても再読込までタブ内で変更できる", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() { throw new DOMException("Storage is disabled", "SecurityError"); }
    });
  });
  await page.goto(BTC_NATIVE_DETAIL);
  const setting = page.getByLabel("騰落率の基準時刻（日本時間）", { exact: true });
  const change = page.getByRole("region", { name: "約定価格の騰落率" });
  await expect(change.getByText("+3.00%", { exact: true })).toBeVisible();
  await openSettings(page);
  await expect(setting).toHaveValue("00:00");
  await setting.fill("09:07");
  await setting.blur();
  await expect(setting).toHaveValue("09:07");
  await expect(page.getByRole("status").filter({
    hasText: "保存できないため、再読込するまでこのタブ内だけに適用しています"
  })).toBeVisible();
  await returnToNative(page);
  await expect(change.getByText("-6.36%", { exact: true })).toBeVisible();
});

function priceChangeFixture(url: URL, now: Date, baselinePrice?: number): DailyPriceChange {
  const versionIds: Record<string, number> = {
    "bitget:BTCUSDT": 1,
    "hyperliquid:BTC": 2,
    "bitget:ETHUSDT": 3
  };
  const venueInstrumentId = url.searchParams.get("instrument") ?? "";
  const referenceTime = url.searchParams.get("referenceTime") ?? "";
  const venueInstrumentVersionId = versionIds[venueInstrumentId];
  if (!venueInstrumentVersionId) throw new Error(`未知の騰落率fixture: ${venueInstrumentId}`);
  const baseline = baselinePrice ?? (referenceTime === "09:07" ? 110 : 100);
  return {
    venueInstrumentId,
    venueInstrumentVersionId,
    referenceTime,
    baselineAt: new Date(dailyBaselineAt(now.getTime(), referenceTime)).toISOString(),
    generatedAt: now.toISOString(),
    status: "ready",
    reason: null,
    baselinePrice: baseline,
    currentPrice: 103,
    currentCandleAt: new Date(Math.floor(now.getTime() / 60_000) * 60_000).toISOString(),
    changePercent: (103 / baseline - 1) * 100
  };
}

async function browserNow(page: Page): Promise<Date> {
  return new Date(await page.evaluate(() => Date.now()));
}

test("チャートの時間足をVenue切り替えと履歴到着後も保持する", async ({ page }) => {
  await page.goto(BTC_NATIVE_DETAIL);
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await chart.getByRole("button", { name: "1h", exact: true }).click();
  await expect(chart.getByRole("button", { name: "1h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );

  const historyResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/chart-history"
      && url.searchParams.get("instrument") === "hyperliquid:BTC"
      && url.searchParams.get("timeframe") === "1h";
  });
  await clickNativeListButton(page, "BTC hyperliquidを詳細表示");
  await (await historyResponse).finished();
  await expect.poll(async () => (await readSelectionCommand())?.venueInstrumentId)
    .toBe("hyperliquid:BTC");

  await expect(chart).toContainText("hyperliquid:BTC");
  await expect(chart.getByRole("button", { name: "1h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );
  await expect(chart).toHaveAccessibleDescription(/hyperliquid:BTC 1h 120本/);
});

test("チャートのズームを市場データと履歴の定期更新で戻さない", async ({ page }) => {
  await page.clock.install();
  await page.goto(BTC_NATIVE_DETAIL);
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 120本/);
  const candles = chart.locator("canvas").first();
  const period = chart.getByLabel("チャート表示期間", { exact: true });
  await candles.scrollIntoViewIfNeeded();
  await settleChartPaint(page);
  const initialImage = await canvasImage(candles);
  const initialPeriod = await period.textContent();
  const bounds = await candles.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) throw new Error("ローソク足canvasの表示領域がありません");

  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.wheel(0, -400);
  await expect(period).not.toHaveText(initialPeriod ?? "");
  await page.mouse.move(0, 0);
  await expect.poll(() => canvasImage(candles)).not.toBe(initialImage);
  await settleChartPaint(page);
  const zoomedImage = await canvasImage(candles);
  const zoomedPeriod = await period.textContent();

  const response = await page.waitForResponse(
    (response) => response.url().endsWith("/api/market-data") && response.status() === 200,
    { timeout: 8_000 }
  );
  await response.finished();
  await settleChartPaint(page);
  await expect(period).toHaveText(zoomedPeriod ?? "");
  expect(await canvasImage(candles)).toBe(zoomedImage);

  const historyResponse = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/api/chart-history"
      && response.status() === 200
  );
  await page.clock.fastForward(60_000);
  await (await historyResponse).finished();
  await settleChartPaint(page);
  await expect(period).toHaveText(zoomedPeriod ?? "");
  expect(await canvasImage(candles)).toBe(zoomedImage);
});

test("チャートの古い履歴応答で新しく選んだ時間足を上書きしない", async ({ page }) => {
  const now = new Date();
  let receiveDelayedRoute: (route: Route) => void = () => undefined;
  const delayedRoute = new Promise<Route>((resolve) => { receiveDelayedRoute = resolve; });
  await page.route("**/api/chart-history?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("timeframe") === "1h") {
      receiveDelayedRoute(route);
      return;
    }
    await route.fallback();
  });
  await page.goto(BTC_NATIVE_DETAIL);
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 120本/);
  await chart.getByRole("button", { name: "1h", exact: true }).click();
  const pending = await delayedRoute;
  await chart.getByRole("button", { name: "4h", exact: true }).click();
  await expect(chart).toHaveAccessibleDescription(/4h 120本/);

  await pending.fulfill({ json: chartHistoryFixture(new URL(pending.request().url()), now) });
  await settleChartPaint(page);
  await expect(chart.getByRole("button", { name: "4h", exact: true })).toHaveAttribute(
    "aria-pressed", "true"
  );
  await expect(chart).toHaveAccessibleDescription(/4h 120本/);
});

test("チャートを過去へスクロールすると履歴を追加し表示位置を保つ", async ({ page }) => {
  const now = new Date();
  let receiveOlderRoute: (route: Route) => void = () => undefined;
  const olderRoute = new Promise<Route>((resolve) => { receiveOlderRoute = resolve; });
  let firstBucket: string | null = null;
  await page.route("**/api/chart-history?*", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.has("before")) {
      receiveOlderRoute(route);
      return;
    }
    const fixture = chartHistoryFixture(url, now, 180);
    firstBucket = fixture.bars[0].bucketAt;
    await route.fulfill({ json: { ...fixture, hasMore: true, nextBefore: firstBucket } });
  });
  await page.goto(BTC_NATIVE_DETAIL);
  const chart = page.getByRole("region", { name: "価格・出来高" });
  await expect(chart).toHaveAccessibleDescription(/15m 180本/);
  const candles = chart.locator("canvas").first();
  const period = chart.getByLabel("チャート表示期間", { exact: true });
  await candles.scrollIntoViewIfNeeded();
  const bounds = await candles.boundingBox();
  if (!bounds) throw new Error("ローソク足canvasの表示領域がありません");

  const request = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/api/chart-history" && url.searchParams.has("before");
  }, { timeout: 5_000 });
  await page.mouse.move(bounds.x + bounds.width * 0.05, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.05 + 1, bounds.y + bounds.height / 2);
  await page.mouse.move(bounds.x + bounds.width * 0.55, bounds.y + bounds.height / 2, { steps: 10 });
  expect(new URL((await request).url()).searchParams.get("before")).toBe(firstBucket);
  await settleChartPaint(page);
  const scrolledEnd = (await period.textContent())?.split(" — ")[1];
  expect(scrolledEnd).toBeTruthy();
  const pending = await olderRoute;
  await pending.fulfill({ json: chartHistoryFixture(new URL(pending.request().url()), now) });

  await expect(chart).toHaveAccessibleDescription(/15m 300本/);
  await settleChartPaint(page);
  await expect(period).toContainText(` — ${scrolledEnd}`);
  await expect(chart.getByRole("button", { name: "さらに過去を読み込む" })).toHaveCount(0);
  await page.mouse.up();
  await page.mouse.move(0, 0);
});

test.describe("チャートのJST表示", () => {
  test.use({ timezoneId: "America/Los_Angeles" });

  test("1Dは120日分の日足を表示し日足の区切りをJSTで明示する", async ({ page }, testInfo) => {
    await page.goto(BTC_NATIVE_DETAIL);
    const chart = page.getByRole("region", { name: "価格・出来高" });
    const timeframes = chart.getByLabel("チャート時間足", { exact: true });
    await expect(timeframes.getByRole("button", { name: "24h", exact: true })).toHaveCount(0);
    await timeframes.getByRole("button", { name: "1D", exact: true }).click();
    await expect(chart).toHaveAccessibleDescription(/1D 120本/);
    await expect(chart.getByText("日足の区切り 09:00 JST", { exact: true })).toBeVisible();
    await expect(chart.getByLabel("チャート表示期間", { exact: true })).toContainText("JST");
    await expect(chart.getByLabel("チャート表示期間", { exact: true })).toContainText(/09:00.*09:00/);
    await chart.screenshot({ path: testInfo.outputPath("chart-1d.png") });
    await page.screenshot({ path: testInfo.outputPath("page-1d.png"), fullPage: true });

    await clickNativeListButton(page, "ETH bitgetを詳細表示");
    await expect(chart).toHaveAccessibleDescription(/bitget:ETHUSDT 1D 120本/);
    await expect(timeframes.getByRole("button", { name: "1D", exact: true })).toHaveAttribute(
      "aria-pressed", "true"
    );
  });
});

function chartHistoryFixture(url: URL, now: Date, count = 120) {
  const timeframe = url.searchParams.get("timeframe") as Timeframe;
  const seconds = { "5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400, "24h": 86_400 }[timeframe];
  if (!seconds || !url.searchParams.get("instrument")) {
    throw new Error(`履歴要求のinstrument/timeframeが不正です: ${url.pathname}${url.search}`);
  }
  return {
    venueInstrumentId: url.searchParams.get("instrument"),
    venueInstrumentVersionId: Number(url.searchParams.get("expectedVersion")),
    timeframe,
    generatedAt: now.toISOString(),
    bars: Array.from({ length: count }, (_, index) => {
      const open = 64_900 + index * 2 + Math.sin(index / 5) * 50;
      const end = url.searchParams.get("before");
      const endMs = end ? Date.parse(end) : now.getTime();
      const bucketAt = Math.floor(endMs / (seconds * 1_000)) * seconds * 1_000
        - (count - index) * seconds * 1_000;
      return {
        bucketAt: new Date(bucketAt).toISOString(),
        open,
        high: open + 100,
        low: open - 50,
        close: open + 30,
        volumeBase: 10,
        volumeNotional: 650_000,
        complete: true
      };
    }),
    hasMore: false,
    nextBefore: null
  };
}

async function canvasImage(canvas: Locator) {
  const image = await canvas.evaluate((element) => (element as HTMLCanvasElement).toDataURL());
  return createHash("sha256").update(image).digest("hex");
}

async function settleChartPaint(page: Page) {
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function publishArtifacts(now: Date) {
  const generatedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + 5 * 60_000).toISOString();
  const universe: UniverseSnapshotArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "partial",
    qualityReasons: ["contains_non_ready_instruments"],
    parityAssumption: {
      code: "usd_usdc_usdt_reference_only",
      appliedTo: "reference_mark_median_only",
      statement: "USD、USDC、USDTは参考中央値だけ等価扱い"
    },
    items: [
      universeInstrument({
        venue: "bitget",
        sourceSymbol: "BTCUSDT",
        versionId: 1,
        baseAsset: "BTC",
        quoteAsset: "USDT",
        settleAsset: "USDT",
        collateralAsset: "USDT",
        groupId: "crypto:BTC:linear-perp",
        markPrice: 65_000,
        generatedAt,
        medianVenues: ["bitget", "hyperliquid"],
        medianValue: 65_001
      }),
      universeInstrument({
        venue: "hyperliquid",
        sourceSymbol: "BTC",
        versionId: 2,
        baseAsset: "BTC",
        quoteAsset: "USD",
        settleAsset: "USDC",
        collateralAsset: "USDC",
        groupId: "crypto:BTC:linear-perp",
        markPrice: 65_002,
        generatedAt,
        medianVenues: ["bitget", "hyperliquid"],
        medianValue: 65_001
      }),
      universeInstrument({
        venue: "bitget",
        sourceSymbol: "ETHUSDT",
        versionId: 3,
        baseAsset: "ETH",
        quoteAsset: "USDT",
        settleAsset: "USDT",
        collateralAsset: "USDT",
        groupId: "crypto:ETH:linear-perp",
        markPrice: 3_500,
        generatedAt,
        medianVenues: ["bitget"],
        medianValue: null
      })
    ]
  };
  const chart: MarketChartArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
    venueInstrumentId: "bitget:BTCUSDT",
    timeframes: [
      {
        timeframe: "15m",
        seconds: 900,
        bars: [
          {
            bucketAt: new Date(now.getTime() - 15 * 60_000).toISOString(),
            open: 64_900,
            high: 65_050,
            low: 64_850,
            close: 65_000,
            volumeBase: 10,
            volumeNotional: 650_000,
            tradeCount: 20,
            finality: "confirmed",
            sourceAt: generatedAt,
            observedAt: generatedAt,
            sourceBarCount: 15,
            expectedSourceBarCount: 15,
            complete: true,
            qualityReasons: []
          }
        ]
      }
    ]
  };
  const selected: SelectedMarketArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
    disclaimers: {
      includesFees: false,
      predictsFutureImpact: false,
      confirmsOrderAvailability: false,
      statement: "Reference onlyの板上概算です。"
    },
    selection: {
      selectionId: "e2e-selection",
      groupId: "crypto:BTC:linear-perp",
      primaryVenueInstrumentId: "bitget:BTCUSDT",
      expiresAt,
      instruments: [
        selectedInstrument("bitget", "BTCUSDT", "USDT", 1, 65_000, generatedAt),
        selectedInstrument("hyperliquid", "BTC", "USD", 2, 65_002, generatedAt)
      ],
      trades: [
        {
          venueInstrumentId: "bitget:BTCUSDT",
          venueInstrumentVersionId: 1,
          venue: "bitget",
          sourceSymbol: "BTCUSDT",
          tradeId: "trade-1",
          side: "buy",
          price: 65_000,
          sizeBase: 0.01,
          sourceAt: null,
          receivedAt: generatedAt
        }
      ]
    }
  };
  const service: MarketServiceStateArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "partial",
    qualityReasons: ["artifact_write_failure"],
    collectors: [],
    catalog: {
      status: "ready",
      latestAt: generatedAt,
      ageSeconds: 1,
      maxAgeSeconds: 1_800,
      errorCode: null
    },
    l1: {
      status: "ready",
      latestAt: generatedAt,
      ageSeconds: 1,
      maxAgeSeconds: 120,
      errorCode: null
    },
    artifacts: [
      artifactState("universe-snapshot.json", generatedAt),
      artifactState("market-chart.json", generatedAt),
      artifactState("selected-market.json", generatedAt),
      artifactState("service-state.json", generatedAt)
    ]
  };

  await Promise.all([
    atomicWrite(resolve(artifactRoot, "universe-snapshot.json"), universe),
    atomicWrite(resolve(artifactRoot, "market-chart.json"), chart),
    atomicWrite(resolve(artifactRoot, "selected-market.json"), selected)
  ]);
  await atomicWrite(resolve(artifactRoot, "service-state.json"), service);
}

function universeInstrument(input: {
  venue: "bitget" | "hyperliquid";
  sourceSymbol: string;
  versionId: number;
  baseAsset: string;
  quoteAsset: string;
  settleAsset: string;
  collateralAsset: string;
  groupId: string;
  markPrice: number;
  generatedAt: string;
  medianVenues: ("bitget" | "hyperliquid")[];
  medianValue: number | null;
}): UniverseInstrumentArtifact {
  const instrumentId = `${input.venue}:${input.sourceSymbol}`;
  return {
    venueInstrumentId: instrumentId,
    venueInstrumentVersionId: input.versionId,
    groupId: input.groupId,
    mappingMethod: "exact_base_heuristic",
    venue: input.venue,
    sourceSymbol: input.sourceSymbol,
    baseAsset: input.baseAsset,
    quoteAsset: input.quoteAsset,
    settleAsset: input.settleAsset,
    collateralAsset: input.collateralAsset,
    active: true,
    marketType: "linear_perpetual",
    executionModel: "clob",
    catalog: {
      sourceKind: "native_rest",
      endpoint: `/e2e/catalog/${input.venue}`,
      documentationUrl: null,
      payloadHash: `catalog-${instrumentId}`,
      observedAt: input.generatedAt,
      sourceAt: null
    },
    quality: "ready",
    qualityReasons: [],
    ageSeconds: 1,
    collectorRunId: "e2e-run",
    cycleAt: input.generatedAt,
    observedAt: input.generatedAt,
    sourceAt: null,
    sourcePayloadHash: `l1-${instrumentId}`,
    errorCode: null,
    markPrice: input.markPrice,
    referencePrice: input.markPrice + 1,
    referencePriceKind: input.venue === "hyperliquid" ? "oracle" : "index",
    bestBid: input.markPrice - 1,
    bestAsk: input.markPrice + 1,
    fundingRateRaw: 0.0001,
    fundingIntervalSeconds: input.venue === "hyperliquid" ? 3_600 : 28_800,
    fundingRatePerHour: 0.0000125,
    nextFundingAt: input.generatedAt,
    openInterestRaw: 10,
    openInterestRawUnit: "base",
    openInterestBase: 10,
    openInterestNotional: input.markPrice * 10,
    volume24hRaw: input.markPrice * 100,
    volume24hUnit: "quote",
    referenceMarkMedian: {
      status: input.medianValue === null ? "unavailable" : "ready",
      value: input.medianValue,
      venueCount: input.medianVenues.length,
      venues: input.medianVenues,
      cycleAt: input.generatedAt,
      maxAgeSeconds: 1,
      skewSeconds: 0,
      unavailableReason: input.medianValue === null ? "insufficient_venues" : null,
      parityAssumptionCode: "usd_usdc_usdt_reference_only"
    }
  };
}

function selectedInstrument(
  venue: "bitget" | "hyperliquid",
  sourceSymbol: string,
  quoteAsset: string,
  versionId: number,
  markPrice: number,
  generatedAt: string
) {
  return {
    venueInstrumentId: `${venue}:${sourceSymbol}`,
    venueInstrumentVersionId: versionId,
    venue,
    sourceSymbol,
    quoteAsset,
    depthReceivedAt: generatedAt,
    depthAgeSeconds: 1,
    quality: "ready" as const,
    qualityReasons: [],
    bids: [
      { price: markPrice - 1, sizeBase: 1 },
      { price: markPrice - 2, sizeBase: 2 }
    ],
    asks: [
      { price: markPrice + 1, sizeBase: 1 },
      { price: markPrice + 2, sizeBase: 2 }
    ],
    bookWalks: [100, 500, 1_000].map((notionalQuote, index) => ({
      notionalQuote,
      buy: {
        baseSize: notionalQuote / markPrice,
        averagePrice: markPrice + index + 1,
        topPriceImpactBps: index + 0.1
      },
      sell: {
        baseSize: notionalQuote / markPrice,
        averagePrice: markPrice - index - 1,
        topPriceImpactBps: index + 0.1
      },
      buyUnavailableReason: null,
      sellUnavailableReason: null,
      includesFees: false as const,
      predictsFutureImpact: false as const,
      confirmsOrderAvailability: false as const
    }))
  };
}

function artifactState(name: string, generatedAt: string) {
  return { name, status: "ready" as const, generatedAt, errorCode: null };
}

async function atomicWrite(path: string, value: unknown) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value)}\n`, "utf-8");
  await rename(temporary, path);
}

async function publishSyntheticAuditForBitget(rowCount = 10, allDifferent = false): Promise<string> {
  const inputDir = resolve(runtimeRoot, "audit-input");
  await mkdir(inputDir, { recursive: true });
  const now = new Date();
  const startMs = Math.floor(now.getTime() / 60_000) * 60_000 - (rowCount + 30) * 60_000;
  const stamp = (minute: number) => new Date(startMs + minute * 60_000).toISOString();
  const series = {
    venue: "bitget", source_symbol: "BTCUSDT", venue_instrument_version_id: 1,
    definition_sha256: "f".repeat(64), base_asset: "BTC", quote_asset: "USDT",
    settle_asset: "USDT", price_kind: "trade", interval_seconds: 60
  };
  const records = Array.from({ length: rowCount }, (_, index) => ({
    venue_instrument_version_id: 1, bucket_at: stamp(index),
    open_price: String(100 + index), high_price: String(102 + index),
    low_price: String(99 + index), close_price: String(100 + index),
    volume_base: "1", volume_notional: null, trade_count: 1,
    finality: "derived_final", source_at: stamp(index), observed_at: stamp(index + 1)
  }));
  const left = { schema_version: 1, source_label: "e2e-left", series, records };
  const right = { schema_version: 1, source_label: "e2e-right", series, records: records.map((row, index) =>
    allDifferent || index === 5 ? { ...row, close_price: String(100 + index + 0.5) } : row) };
  await atomicWrite(resolve(inputDir, "left.json"), left);
  await atomicWrite(resolve(inputDir, "right.json"), right);
  await atomicWrite(resolve(inputDir, "request.json"), {
    schemaVersion: 1,
    target: { venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1 },
    leftPath: "left.json", rightPath: "right.json",
    leftSource: { sourceId: "e2e-left", label: "合成保存足 A", snapshotCreatedAt: now.toISOString() },
    rightSource: { sourceId: "e2e-right", label: "合成保存足 B", snapshotCreatedAt: now.toISOString() },
    comparisonKind: "snapshot_revision", evidenceKind: "synthetic",
    windowStart: stamp(0), windowEnd: stamp(rowCount), dataAsOf: stamp(rowCount + 3),
    returnMinutes: 5, compareVolumeBase: true,
    tolerances: { priceAbsTol: "0", priceRelTol: "0", volumeAbsTol: "0",
      volumeRelTol: "0", returnTolBps: "0" }
  });
  const result = await new Promise<{ code: number | null; stdout: string; stderr: string }>((resolveResult, reject) => {
    const child = spawn("uv", ["run", "--no-sync", "python", "-m",
      "prep_watchdeck_market.candle_audit_publication", "--request",
      resolve(inputDir, "request.json"), "--state-dir", runtimeRoot], {
      cwd: resolve(process.cwd(), "../market-core"), stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (part: Buffer) => { stdout += part.toString(); });
    child.stderr.on("data", (part: Buffer) => { stderr += part.toString(); });
    child.on("error", reject);
    child.on("close", (code) => resolveResult({ code, stdout, stderr }));
  });
  expect(result.code, result.stderr).toBe(1);
  const resultJson = JSON.parse(result.stdout) as { runId: string; outcome: string };
  expect(resultJson.outcome).toBe("differences");
  return resultJson.runId;
}

async function readSelectionCommand(): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(await readFile(selectionPath, "utf-8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}

test("P01 日本語で記録する比較担当は保存応答中のChromium IME候補・focus・別銘柄下書きを保持する", async ({ page }, testInfo) => {
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await page.getByLabel("理由", { exact: true }).fill("Aの記録");
  await page.getByLabel("短い観測メモ").fill("保存する本文");
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let committed = false;
  await page.route("**/api/market-past-notes", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const response = await route.fetch(); committed = true;
    await held; await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  await expect.poll(() => committed).toBe(true);
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await page.getByLabel("短い観測メモ").fill("Bの下書き");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  const note = page.getByLabel("短い観測メモ");
  await expect(note).toHaveValue("保存する本文");
  await note.focus();
  await note.press("End");
  const ime = await browserIme(page, note);
  let events: BrowserImeEvent[] = [];
  try {
    await ime.compose("・ついかにゅうりょくにほんご");
    await expect(note).toHaveValue("保存する本文・ついかにゅうりょくにほんご");
    await ime.compose("・追加入力日本語");
    await expect(note).toHaveValue("保存する本文・追加入力日本語");
    const beforeResponse = await ime.events();
    expect(beforeResponse.some(event => event.type === "compositionstart" && event.isTrusted)).toBe(true);
    expect(beforeResponse.some(event => event.type === "input" && event.isTrusted && event.isComposing)).toBe(true);
    expect(beforeResponse.filter(event => event.type === "compositionend")).toHaveLength(0);
    const returned = page.waitForResponse(response => response.url().endsWith("/api/market-past-notes") && response.request().method() === "POST");
    release();
    await (await returned).finished();
    await expect(page.getByText("bitget:BTCUSDT に保存しました", { exact: true })).toBeVisible();
    await expect(note).toHaveValue("保存する本文・追加入力日本語");
    await expect(note).toBeFocused();
    expect((await ime.events()).filter(event => event.type === "compositionend")).toHaveLength(0);
    const screenshotPath = testInfo.outputPath("p01-active-composition.png");
    await page.screenshot({ path: screenshotPath });
    await testInfo.attach("p01-active-composition.png", { path: screenshotPath, contentType: "image/png" });
    await ime.commit("・追加入力日本語");
    await expect(note).toHaveValue("保存する本文・追加入力日本語");
    await expect(note).toBeFocused();
    await ime.compose("・とりけし");
    await expect(note).toHaveValue("保存する本文・追加入力日本語・とりけし");
    await ime.cancel();
    await expect(note).toHaveValue("保存する本文・追加入力日本語");
    await expect(note).toBeFocused();
    events = await ime.events();
    const eventPath = testInfo.outputPath("p01-browser-ime.json");
    await writeFile(eventPath, JSON.stringify({ persona: "P01 日本語で記録する比較担当", boundary: "Chromium CDP composition; OS IME and physical device unverified", viewport: page.viewportSize(), saveResponseDeliveredDuringComposition: true, events }, null, 2));
    await testInfo.attach("p01-browser-ime.json", { path: eventPath, contentType: "application/json" });
    expect(events.some(event => event.type === "compositionend" && event.data === "・追加入力日本語")).toBe(true);
    expect(events.filter(event => event.type === "compositionend")).toHaveLength(2);
    // Chrome CDP commit/cancel produce an untrusted compositionend even on an
    // empty HTML input. All preedit/candidate editing events must be trusted.
    expect(events.filter(event => event.type !== "compositionend").every(event => event.isTrusted)).toBe(true);
  } finally {
    release();
    await ime.close();
  }
  await expect(page.locator(".note-list")).toContainText("保存する本文");
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await expect(note).toHaveValue("Bの下書き");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await expect(note).toHaveValue("保存する本文・追加入力日本語");
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  await expect(page.locator(".note-list")).toContainText("保存する本文・追加入力日本語");
  await expect(note).toHaveValue("");
  const saved = await (await page.request.get("/api/market-past-notes?venueInstrumentId=bitget:BTCUSDT")).json();
  expect(saved.notes[0]).toMatchObject({
    venueInstrumentId: "bitget:BTCUSDT", reason: "Aの記録", note: "保存する本文・追加入力日本語"
  });
  const draft = await page.evaluate(() => sessionStorage.getItem("market-note-draft:bitget:ETHUSDT/3"));
  expect(JSON.parse(draft!)).toMatchObject({ note: "Bの下書き" });
  await page.reload();
  await expect(page.getByRole("region", { name: "価格・出来高" })).toContainText("bitget:BTCUSDT");
  if (testInfo.project.name === "mobile-390") {
    await expect(page.getByRole("button", { name: "一覧へ戻る", exact: true })).toBeVisible();
  }
  await expect(page.locator(".note-list")).toContainText("保存する本文・追加入力日本語");
  await expect(note).toHaveValue("");
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await expect(note).toHaveValue("Bの下書き");
});

test("2タブのメモCASと別favorite・savedView競合・旧selection heartbeatを分離する", async ({ page, context }) => {
  const other = await context.newPage();
  try {
    await page.goto("/?mode=native");
    await other.route("**/api/chart-history?*", route => route.fulfill({ json: chartHistoryFixture(new URL(route.request().url()), new Date()) }));
    await other.route("**/api/price-change?*", route => route.fulfill({ json: priceChangeFixture(new URL(route.request().url()), new Date()) }));
    await other.goto("/?mode=native");
    for (const tab of [page, other]) {
      await clickNativeListButton(tab, "BTC bitgetを詳細表示");
      await tab.getByLabel("理由", { exact: true }).fill("CAS");
      await tab.getByLabel("短い観測メモ").fill(tab === page ? "先の記録" : "後の下書き");
      await expect(tab.getByRole("button", { name: "注記を保存", exact: true })).toBeEnabled();
    }
    await page.getByRole("button", { name: "注記を保存", exact: true }).click();
    await expect(page.getByText("bitget:BTCUSDT に保存しました", { exact: true })).toBeVisible();
    await other.getByRole("button", { name: "注記を保存", exact: true }).click();
    await expect(other.locator(".notes [role=alert]")).toContainText("past_note_conflict");
    await expect(other.getByLabel("短い観測メモ")).toHaveValue("後の下書き");
    await clickNativeListButton(page, "BTC bitgetをお気に入り登録");
    await clickNativeListButton(other, "ETH bitgetをお気に入り登録");
    await expect.poll(async () => (await (await page.request.get("/api/user-workspace")).json()).favorites.length).toBe(2);
    const stored = await (await page.request.get("/api/user-workspace")).json();
    expect(stored.favorites.map((item: { id: string }) => item.id).sort()).toEqual(["bitget:BTCUSDT", "bitget:ETHUSDT"]);
    await page.reload(); await other.reload();
    for (const tab of [page, other]) {
      await showMarketList(tab);
      await openSection(tab, "表示条件を保存／管理");
    }
    await page.getByLabel("取引所別の表示名").fill("先の表示");
    await other.getByLabel("取引所別の表示名").fill("競合表示");
    await page.getByRole("button", { name: "表示条件を保存" }).click();
    await expect(page.getByLabel("取引所別の保存した表示").locator("option")).toContainText(["選択してください", "先の表示"]);
    await other.getByRole("button", { name: "表示条件を保存" }).click();
    await expect(other.getByRole("alert")).toContainText("別の画面");
    const previous = JSON.parse(await readFile(selectionPath, "utf-8"));
    await clickNativeListButton(other, "ETH bitgetを詳細表示");
    await expect.poll(async () => JSON.parse(await readFile(selectionPath, "utf-8")).venueInstrumentId).toBe("bitget:ETHUSDT");
    const heartbeat = await page.request.post("/api/selection", { headers: { origin: "http://127.0.0.1:4174" }, data: {
      action: "heartbeat", groupId: previous.groupId, venueInstrumentId: previous.venueInstrumentId,
      venueInstrumentVersionId: 1, expectedRequestedAt: previous.requestedAt
    } });
    expect(heartbeat.status()).toBe(409);
    expect(JSON.parse(await readFile(selectionPath, "utf-8")).venueInstrumentId).toBe("bitget:ETHUSDT");
  } finally { await other.close(); }
});

test("お気に入り登録と解除の連打は遅延応答後も最後の意図を保持する", async ({ page }) => {
  await page.goto("/?mode=native");
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let captured = false;
  await page.route("**/api/user-workspace", async route => {
    if (route.request().method() !== "POST" || captured) return route.fallback();
    const response = await route.fetch(); captured = true;
    await held; await route.fulfill({ response });
  });
  await clickNativeListButton(page, "BTC bitgetをお気に入り登録");
  await expect.poll(() => captured).toBe(true);
  await clickNativeListButton(page, "BTC bitgetをお気に入り解除");
  release();
  await expect.poll(async () => (await (await page.request.get("/api/user-workspace")).json()).favorites).toEqual([]);
  await page.reload();
  await expect(page.getByRole("button", { name: "BTC bitgetをお気に入り登録" })).toHaveAttribute("aria-pressed", "false");
});

test("保存APIのHTTP異常系は状態と非公開情報を保護する", async ({ request }) => {
  const origin = "http://127.0.0.1:4174";
  for (const endpoint of ["selection", "market-past-notes", "user-workspace"]) {
    for (const scenario of [
      { status: 403, headers: { origin: "https://example.invalid", "content-type": "application/json" }, data: "{}" },
      { status: 400, headers: { origin, "content-type": "text/plain" }, data: "{}" },
      { status: 400, headers: { origin, "content-type": "application/json" }, data: "{bad" },
      { status: 400, headers: { origin, "content-type": "application/json" }, data: '{"unexpected":true}' },
      { status: 413, headers: { origin, "content-type": "application/json" }, data: JSON.stringify({ note: "あ".repeat(24_000) }) }
    ]) {
      const response = await request.post(`/api/${endpoint}`, scenario);
      expect(response.status(), endpoint).toBe(scenario.status);
      expect(await response.text()).not.toMatch(/\/home\/|stack|postgresql:|password/i);
    }
  }
  const valid = { venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1,
    reason: "境界", note: "<img src=x onerror=alert(1)>", expectedRevisionToken: "absent" };
  const post = (data: unknown) => request.post("/api/market-past-notes", { headers: { origin }, data });
  expect((await post({ ...valid, venueInstrumentVersionId: 999 })).status()).toBe(409);
  expect((await post({ ...valid, venueInstrumentId: "../../escape" })).status()).toBe(409);
  const context = { kind: "ui-observation-v1", venueInstrumentId: valid.venueInstrumentId,
    venueInstrumentVersionId: 1, view: "native", capturedAt: new Date().toISOString(),
    metricGenerationId: "test", oi15mPct: 10, trade15mPct: null };
  for (const patch of [{ raw: "secret" }, { view: "reference" }, { oi15mPct: "Infinity" },
    { metricGenerationId: "x".repeat(161) }, { venueInstrumentVersionId: 2 },
    { capturedAt: "2000-01-01T00:00:00Z" }]) {
    expect((await post({ ...valid, context: { ...context, ...patch } })).status()).toBe(400);
  }
  expect((await post({ ...valid, context })).status()).toBe(200);
  expect((await post(valid)).status()).toBe(409);
  await writeFile(resolve(artifactRoot, "universe-snapshot.json"), "{bad");
  expect((await post(valid)).status()).toBe(500);
});

test("隔離DB書込完了からworker・artifact・API・Browserへの後着訂正と停止復帰を測る", async ({ page }, testInfo) => {
  test.skip(!process.env.TEST_DATABASE_URL, "isolated PostgreSQL required");
  test.setTimeout(120_000);
  // Leave enough of a minute for the same-cutoff correction without falsifying source clocks.
  const remaining = 60_000 - Date.now() % 60_000;
  if (remaining < 25_000) await new Promise(resolve => setTimeout(resolve, remaining + 100));
  const child = spawn("uv", ["run", "python", "-m", "tests.metrics_browser_probe", runtimeRoot], {
    cwd: resolve(process.cwd(), "../market-core"), stdio: ["pipe", "pipe", "pipe"]
  });
  let stderr = "";
  child.stderr.on("data", chunk => { stderr += String(chunk); });
  const exited = new Promise<number | null>(resolve => child.on("exit", resolve));
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const events: Record<string, unknown>[] = [];
  async function receive(command?: string) {
    if (command) child.stdin.write(`${command}\n`);
    const line = await lines.next();
    expect(line.done, stderr).not.toBe(true);
    const event = JSON.parse(line.value!);
    events.push(event);
    return event;
  }
  const api: { at: number; generation: string; cutoff: string; value: number | null }[] = [];
  page.on("response", async response => {
    if (!response.url().endsWith("/api/market-metrics") || !response.ok()) return;
    const payload = await response.json().catch(() => null);
    if (payload) api.push({ at: Date.now() / 1000, generation: payload.generationId,
      cutoff: payload.candleCutoff, value: payload.rows[0]?.tradeChange["15m"].value });
  });
  const metricPath = resolve(artifactRoot, "market-metrics.json");
  const panel = page.getByRole("region", { name: "追加の市場変化指標" });
  async function observe(expected: number, label: string, write: Record<string, number>) {
    let artifact!: MarketMetricsArtifact;
    await expect.poll(async () => {
      try { artifact = JSON.parse(await readFile(metricPath, "utf-8")); }
      catch (cause) { if (cause instanceof SyntaxError) return null; throw cause; }
      return Math.round(artifact.rows[0].tradeChange["15m"].value ?? -999);
    }, { timeout: 15_000, intervals: [100] }).toBe(expected);
    const artifactObservedAt = Date.now() / 1000;
    await expect(panel).toContainText(`確定終値: 15m ${expected > 0 ? "+" : ""}${expected.toFixed(2)}%`, { timeout: 12_000 });
    const browserObservedAt = Date.now() / 1000;
    const apiObservation = api.find(event => event.generation === artifact.generationId);
    expect(apiObservation).toBeDefined();
    events.push({ ...write, event: label, artifactObservedAt, apiObservedAt: apiObservation!.at,
      browserObservedAt, generation: artifact.generationId, cutoff: artifact.candleCutoff,
      writeToBrowserSeconds: browserObservedAt - write.writeCompletedAt });
    expect(browserObservedAt - write.writeCompletedAt).toBeLessThan(20);
    return artifact;
  }
  let releaseOld: (() => void) | undefined;
  try {
    const ready = await receive();
    expect(ready.version).toBe(1);
    await expect.poll(async () => readFile(metricPath, "utf-8").then(() => true).catch(() => false)).toBe(true);
    await publishArtifacts(new Date());
    await page.clock.install({ time: Date.now() });
    await page.goto("/?mode=native&instrument=bitget%3ABTCUSDT&version=1");
    await expect(panel).toContainText("確定終値: 15m —");
    const late = await receive("late");
    const first = await observe(10, "late-visible", late);
    const held = new Promise<void>(resolve => { releaseOld = resolve; });
    let captured = false;
    await page.route("**/api/market-metrics", async route => {
      if (captured) return route.fallback();
      const response = await route.fetch(); captured = true;
      await held; await route.fulfill({ response });
    });
    await expect.poll(() => captured, { timeout: 7_000 }).toBe(true);
    const corrected = await receive("correct");
    const second = await observe(-5, "correction-visible", corrected);
    expect(second.candleCutoff).toBe(first.candleCutoff);
    const oldResponse = page.waitForResponse(response => response.url().endsWith("/api/market-metrics"));
    releaseOld?.();
    await (await oldResponse).finished();
    await settleChartPaint(page);
    await expect(panel).toContainText("確定終値: 15m -5.00%");
    await receive("stop");
    const broken = "{isolated broken metrics";
    await writeFile(metricPath, broken);
    const stoppedWrite = await receive("resume-write");
    expect(await readFile(metricPath, "utf-8")).toBe(broken);
    await receive("restart");
    await observe(20, "restart-visible", stoppedWrite);
    const preserved = (await readdir(artifactRoot)).filter(name => name.startsWith("market-metrics.json.corrupt-"));
    expect(preserved).toHaveLength(1);
    expect(await readFile(resolve(artifactRoot, preserved[0]), "utf-8")).toBe(broken);
    events.push({ event: "corrupt-original-preserved", bytes: Buffer.byteLength(broken) });
    const timedOut = receive("timeout");
    // Essential artifacts keep their normal independent refresh during the metrics fault.
    await publishArtifacts(new Date());
    await page.route("https://s3.tradingview.com/**", route => route.abort());
    await page.route("**/api/rankings?*", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams) }));
    await page.goto("/rankings");
    await page.getByTestId("ranking-row").filter({ hasText: "BTC" }).locator("button.select-row").click();
    await expect(page.frameLocator("iframe").getByRole("status")).toContainText("参照チャートを取得できません");
    await showMarketList(page);
    await page.getByLabel("ランキングの銘柄検索").fill("ETH");
    await expect(page.getByTestId("ranking-row")).toHaveCount(1);
    const timeoutResult = await timedOut;
    expect(timeoutResult).toMatchObject({ event: "timeout", maximumConnections: 1, artifactUnchanged: true });
    await publishArtifacts(new Date());
    await page.goto("/?mode=native");
    await expect(page.getByRole("heading", { name: "銘柄一覧" })).toBeVisible();
    await clickNativeListButton(page, "BTC bitgetをお気に入り登録");
    await expect(page.getByRole("button", { name: "BTC bitgetをお気に入り解除" })).toHaveAttribute("aria-pressed", "true");
    await clickNativeListButton(page, "BTC bitgetを詳細表示");
    await receive("stop");
    await page.clock.fastForward(310_000);
    await expect(panel).not.toContainText("+20.00%");
    events.push({ event: "stopped-clock-expired", advancedSeconds: 310 });
  } finally {
    releaseOld?.();
    child.stdin.write("quit\n");
    expect(await exited, stderr).toBe(0);
    await writeFile(testInfo.outputPath("metrics-pipeline.json"), JSON.stringify({
      timingMeaning: "commitRequestedAt/writeCompletedAt bracket the client commit acknowledgement; observed/source timestamps are not commit timestamps. Poll is 5s, not a total latency guarantee.",
      events, api
    }, null, 2));
  }
});

test("Aの保存応答がB表示中に到着してもBの下書きと保存状態を守る", async ({ page }) => {
  await page.goto(BTC_NATIVE_DETAIL);
  await page.getByLabel("理由", { exact: true }).fill("A保存");
  await page.getByLabel("短い観測メモ").fill("A本文");
  let release!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  let committed = false;
  await page.route("**/api/market-past-notes", async route => {
    if (route.request().method() !== "POST") return route.fallback();
    const response = await route.fetch(); committed = true;
    await held; await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  await expect.poll(() => committed).toBe(true);
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await page.getByLabel("短い観測メモ").fill("B本文");
  const returned = page.waitForResponse(r => r.url().endsWith("/api/market-past-notes") && r.request().method() === "POST");
  release(); await (await returned).finished();
  await expect(page.getByLabel("短い観測メモ")).toHaveValue("B本文");
  await expect(page.getByRole("button", { name: "注記を保存", exact: true })).toBeEnabled();
  await expect(page.locator(".note-list")).toHaveCount(0);
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await expect(page.locator(".note-list")).toContainText("A本文");
  await expect(page.getByRole("button", { name: "注記を保存", exact: true })).toBeEnabled();
});

test("URL初期復元はselectionを送らずhidden中heartbeatを停止する", async ({ page }) => {
  const actions: string[] = [];
  page.on("request", request => {
    if (request.url().endsWith("/api/selection") && request.method() === "POST") actions.push(request.postDataJSON().action);
  });
  await page.clock.install();
  await page.goto("/?mode=native&instrument=bitget%3AETHUSDT&version=3");
  await expect(page.getByRole("region", { name: "価格・出来高" })).toContainText("bitget:ETHUSDT");
  await page.clock.fastForward(300_000);
  expect(actions).toEqual([]);
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await openSection(page, "選択データの監視状態");
  await expect(page.getByText("詳細データを要求しました", { exact: true })).toBeVisible();
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.clock.fastForward(600_000);
  expect(actions).toEqual(["select"]);
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.clock.fastForward(300_000);
  await expect.poll(() => actions).toEqual(["select", "heartbeat"]);
});

test("selectionの応答abort後もserver保存を認識して次の選択を維持する", async ({ page }) => {
  let aborted = false;
  await page.route("**/api/selection", async route => {
    if (aborted) return route.fallback();
    const response = await route.fetch(); expect(response.status()).toBe(200);
    aborted = true; await route.abort("failed");
  });
  await page.goto("/?mode=native");
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await expect.poll(async () => (await readSelectionCommand())?.venueInstrumentId).toBe("bitget:ETHUSDT");
  await expect(page.getByRole("region", { name: "価格・出来高" })).toContainText("bitget:ETHUSDT");
  await clickNativeListButton(page, "BTC bitgetを詳細表示");
  await expect.poll(async () => (await readSelectionCommand())?.venueInstrumentId).toBe("bitget:BTCUSDT");
  await openSection(page, "選択データの監視状態");
  await expect(page.getByText("詳細データを要求しました", { exact: true })).toBeVisible();
});

test("参照メモは出所と時刻を保存しXSS文字列を実行せずnativeでも再読込できる", async ({ page }) => {
  await page.route("https://s3.tradingview.com/**", route => route.abort());
  await page.route("**/api/rankings?*", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams) }));
  await page.goto("/rankings");
  await page.getByTestId("ranking-row").filter({ hasText: "BTC" }).locator("button.select-row").click();
  await expect(page.frameLocator("iframe").getByRole("status")).toContainText("参照チャートを取得できません");
  await page.getByText("この参照市場の観測メモ", { exact: true }).click();
  await page.getByLabel("理由", { exact: true }).fill("参照を記録");
  const text = '<img src=x onerror="window.__xss=1">';
  await page.getByLabel("短い観測メモ").fill(text);
  await page.getByLabel("保存時の指標を添付する").check();
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  await expect(page.locator(".note-list")).toContainText(text);
  await expect(page.locator(".note-list img")).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  const notes = await (await page.request.get("/api/market-past-notes?venueInstrumentId=bitget:BTCUSDT")).json();
  expect(notes.notes[0].context).toMatchObject({ view: "reference", venueInstrumentId: "bitget:BTCUSDT", reference: { source: "bybit", symbol: "BTCUSDT", period: "15m", returnPct: 2.125 } });
  await page.getByRole("link", { name: "Bitget · BTCUSDT を確認" }).click();
  await expect(page.locator(".note-list")).toContainText("保存時の参照: bybit");
});

test("native L1は120秒境界とhidden復帰でもreadyを残さずFundingを推測しない", async ({ page }) => {
  const path = resolve(artifactRoot, "universe-snapshot.json");
  const universe = JSON.parse(await readFile(path, "utf-8")) as UniverseSnapshotArtifact;
  const item = universe.items.find(x => x.venueInstrumentId === "bitget:BTCUSDT")!;
  item.fundingIntervalSeconds = null; item.fundingRatePerHour = null; item.nextFundingAt = null;
  await writeFile(path, JSON.stringify(universe));
  const baseline = Date.parse(item.observedAt!);
  const stamp = new Date(baseline).toISOString();
  const metric = { value: 17, availability: "available", reasonCode: null, startAt: stamp, endAt: stamp,
    startValue: 100, endValue: 117, endSourceAt: stamp, endObservedAt: stamp, endFinality: null, unit: "base" };
  await page.route("**/api/market-metrics", route => route.fulfill({ json: {
    schemaVersion: 1, metricVersion: "native-endpoints-v1", generationId: "boundary", generatedAt: stamp, candleCutoff: stamp,
    rows: [{ venueInstrumentId: item.venueInstrumentId, venueInstrumentVersionId: item.venueInstrumentVersionId,
      oiChange: { "15m": metric, "1h": metric }, tradeChange: { "15m": metric, "1h": metric, "24h": metric } }]
  } }));
  const metricsPanel = page.getByRole("region", { name: "追加の市場変化指標" });
  await page.clock.install({ time: baseline });
  await page.goto(BTC_NATIVE_DETAIL);
  if (await page.evaluate(() => matchMedia("(max-width: 48rem)").matches)) {
    await expect(page.getByRole("button", { name: "一覧へ戻る", exact: true })).toBeVisible();
  }
  const mobile = await showMarketList(page);
  await openSection(page, "絞り込み条件");
  await page.getByRole("button", { name: "行順を固定", exact: true }).click();
  if (mobile) {
    await page.goForward();
    await expect(page.getByRole("button", { name: "一覧へ戻る", exact: true })).toBeVisible();
  }
  const l1 = page.locator(".l1-block");
  await expect(l1).toContainText("Funding周期");
  await expect(l1.locator("div").filter({ has: page.locator("dt", { hasText: /^Funding周期$/ }) })).toContainText("未確認");
  await expect(l1.locator("div").filter({ has: page.locator("dt", { hasText: /^次回Funding$/ }) })).toContainText("未確認");
  await page.clock.setFixedTime(baseline + 120_000);
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  const row = page.locator(".universe tbody tr").filter({ has: page.locator('.instrument-select[aria-label="BTC bitgetを詳細表示"]') });
  await expect(row).not.toContainText("期限切れ");
  await expect(metricsPanel).toContainText("数量OI: 15m +17.00%");
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
  await page.clock.setFixedTime(baseline + 120_001);
  await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect(row).toContainText("期限切れ");
  await expect(metricsPanel).not.toContainText("+17.00%");
  await clickNativeListButton(page, "ETH bitgetを詳細表示");
  await expect(l1).toContainText("経過（次回未確認）");
});

for (const releaseOrder of ["before", "after"] as const) {
  test(`catalog version変更中の過去ページと旧metricsを拒否する（旧応答${releaseOrder}）`, async ({ page }) => {
    let older: Route | undefined;
    const now = new Date();
    await page.route("**/api/chart-history?*", async route => {
      const url = new URL(route.request().url());
      if (url.searchParams.has("before")) { older = route; return; }
      const old = url.searchParams.get("expectedVersion") === "1";
      const fixture = chartHistoryFixture(url, now, old ? 180 : 90);
      await route.fulfill({ json: { ...fixture, hasMore: old, nextBefore: old ? fixture.bars[0].bucketAt : null } });
    });
    const metric = { value: 10, availability: "available", reasonCode: null, startAt: now.toISOString(), endAt: now.toISOString(),
      startValue: 100, endValue: 110, endSourceAt: now.toISOString(), endObservedAt: now.toISOString(), endFinality: null, unit: "base" };
    let responseVersion = 1;
    let hold = false;
    let oldMetrics: Route | undefined;
    const metrics = (version: number) => ({ schemaVersion: 1, metricVersion: "native-endpoints-v1", generationId: `g${version}`,
      generatedAt: now.toISOString(), candleCutoff: now.toISOString(), timingPolicy: { candleLagSeconds: 180, candleMaxAgeSeconds: 300 },
      rows: [{ venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: version, venue: "bitget", sourceSymbol: "BTCUSDT", quoteAsset: "USDT", settleAsset: "USDT", priceTick: null,
        oiChange: { "15m": { ...metric, value: version * 10 }, "1h": metric }, tradeChange: { "15m": metric, "1h": metric, "24h": metric } }] });
    await page.route("**/api/market-metrics", async route => {
      if (hold && !oldMetrics) { oldMetrics = route; return; }
      await route.fulfill({ json: metrics(responseVersion) });
    });
    await page.goto(BTC_NATIVE_DETAIL);
    const chart = page.getByRole("region", { name: "価格・出来高" });
    const panel = page.getByRole("region", { name: "追加の市場変化指標" });
    await expect(chart).toHaveAccessibleDescription(/15m 180本/);
    await expect(panel).toContainText("数量OI: 15m +10.00%");
    await chart.getByRole("button", { name: "さらに過去を読み込む" }).click();
    await expect.poll(() => Boolean(older)).toBe(true);
    hold = true;
    await expect.poll(() => Boolean(oldMetrics), { timeout: 7_000 }).toBe(true);
    const path = resolve(artifactRoot, "universe-snapshot.json");
    const universe = JSON.parse(await readFile(path, "utf-8")) as UniverseSnapshotArtifact;
    universe.items.find(item => item.venueInstrumentId === "bitget:BTCUSDT")!.venueInstrumentVersionId = 101;
    await writeFile(path, JSON.stringify(universe));
    responseVersion = 101;
    await expect(chart).toHaveAccessibleDescription(/15m 90本/, { timeout: 7_000 });
    const releaseOld = async () => {
      const oldResponse = page.waitForResponse(response => response.request() === oldMetrics!.request());
      await oldMetrics!.fulfill({ json: metrics(1) });
      await (await oldResponse).finished();
      await older!.fulfill({ json: chartHistoryFixture(new URL(older!.request().url()), now, 120) });
      await settleChartPaint(page);
    };
    if (releaseOrder === "before") await releaseOld();
    await expect(panel).toContainText("数量OI: 15m +1010.00%", { timeout: 7_000 });
    if (releaseOrder === "after") await releaseOld();
    await expect(chart).toHaveAccessibleDescription(/15m 90本/);
    await expect(panel).toContainText("数量OI: 15m +1010.00%");
  });
}

test("selectionとworkspaceの500応答は内部情報を漏らさず原本を保つ", async ({ request }) => {
  const headers = { origin: "http://127.0.0.1:4174" };
  const workspace = resolve(runtimeRoot, "user-workspace.json");
  await writeFile(workspace, "{bad workspace");
  const response = await request.post("/api/user-workspace", { headers, data: {
    action: "setFavorite", target: { kind: "instrument", id: "bitget:BTCUSDT", version: 1 }, enabled: false
  } });
  expect(response.status()).toBe(500);
  expect(await response.text()).not.toMatch(/\/home\/|stack|postgresql:|password/i);
  expect(await readFile(workspace, "utf-8")).toBe("{bad workspace");
  await writeFile(resolve(artifactRoot, "universe-snapshot.json"), "{bad universe");
  const selection = await request.post("/api/selection", { headers, data: {
    action: "select", groupId: "crypto:BTC:linear-perp", venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1
  } });
  expect(selection.status()).toBe(500);
  expect(await selection.text()).not.toMatch(/\/home\/|stack|postgresql:|password/i);
  expect(await readSelectionCommand()).toBeNull();
});
