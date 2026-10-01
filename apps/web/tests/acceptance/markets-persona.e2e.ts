import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { resolve } from "node:path";
import type { MarketPastNote } from "../../src/lib/market-past-note/market-past-note";
import type { UserWorkspace } from "../../src/lib/server/user-workspace-repository";
import type { RankingResponse } from "../../src/lib/generated/ranking-response";
import type { MarketArtifactBundle } from "../../src/lib/server/market-artifact-repository";
import type { MarketMetricsArtifact } from "../../src/lib/generated/market-metrics";
import { formatPrice } from "../../src/lib/market/universe-view";
import { formatPriceChange } from "../../src/lib/market/price-change";
import { indicatorLabel } from "../../src/lib/market/ranking";

// This suite consumes actual loopback artifacts and public REST. No market API
// response is mocked, no clock is changed, and every write stays on 4178.
test.beforeEach(async ({ page, context, baseURL }) => {
  if (baseURL !== "http://127.0.0.1:4178") throw new Error("isolated preview required");
  await context.route("**/*", route => {
    const request = route.request();
    return ["GET", "HEAD", "OPTIONS"].includes(request.method())
      || new URL(request.url()).origin === baseURL
      ? route.continue() : route.abort("blockedbyclient");
  });
  await page.addInitScript(() => {
    localStorage.setItem("prep-watchdeck-ranking-chart-interval", "15");
  });
});

test("P00 隔離先以外への書込を送信前に遮断", async ({ page }) => {
  const received: string[] = [];
  const server = createServer((request, response) => {
    received.push(request.method!);
    response.writeHead(200, { "Access-Control-Allow-Origin": "*" });
    response.end("own probe");
  });
  await new Promise<void>(ready => server.listen(0, "127.0.0.1", ready));
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("probe port missing");
    const url = `http://127.0.0.1:${address.port}/own-probe`;
    await page.goto("/api/health");
    expect(await page.evaluate(target => fetch(target).then(r => r.text()), url)).toBe("own probe");
    expect(await page.evaluate(target => fetch(target, { method: "POST", body: "probe" })
      .then(() => false).catch(() => true), url)).toBe(true);
    expect(received).toEqual(["GET"]);
  } finally {
    await new Promise<void>((done, reject) => server.close(error => error ? reject(error) : done()));
  }
});

async function record(page: Page) {
  const errors: string[] = [];
  const writes: string[] = [];
  const blockedWrites: { url: string; error: string | null }[] = [];
  const responses: { path: string; status: number; receivedAt: string; payload: unknown }[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      if (new URL(request.url()).origin === "http://127.0.0.1:4178") writes.push(request.url());
    }
  });
  page.on("requestfinished", request => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())
      && new URL(request.url()).origin !== "http://127.0.0.1:4178") {
      errors.push("external write completed despite guard");
    }
  });
  page.on("requestfailed", request => {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())
      && new URL(request.url()).origin !== "http://127.0.0.1:4178") {
      const error = request.failure()?.errorText ?? null;
      blockedWrites.push({ url: request.url(), error });
      if (error !== "net::ERR_BLOCKED_BY_CLIENT") errors.push("external write was not blocked by guard");
    }
  });
  const pending: Promise<void>[] = [];
  page.on("response", response => {
    const path = new URL(response.url()).pathname;
    if (["/api/rankings", "/api/market-data", "/api/market-metrics", "/api/chart-history", "/api/price-change"].includes(path)) {
      pending.push(response.json().then(payload => {
        responses.push({ path, status: response.status(), receivedAt: new Date().toISOString(), payload });
      }).catch(() => {}));
    }
  });
  return { errors, writes, blockedWrites, responses, flush: () => Promise.all(pending) };
}

async function openReferenceNotes(page: Page) {
  const note = page.getByLabel("短い観測メモ");
  if (!await note.isVisible()) {
    const summary = page.getByText("この参照市場の観測メモ", { exact: true });
    await summary.focus();
    await summary.press("Space");
  }
  await expect(note).toBeVisible();
}

test("P01 実データの参照比較から日本語メモ・native往復・再訪", async ({ page }, info) => {
  const evidence = await record(page);
  await page.goto("/?mode=reference");
  await page.getByLabel("ランキングの並び順").selectOption("turnover");
  const selected = page.locator('[data-testid="ranking-row"][data-asset="BTC"] .select-row');
  await expect(selected).toBeVisible();
  await selected.focus();
  await selected.press("Enter");
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await evidence.flush();
  const ranking = evidence.responses.filter(r => r.path === "/api/rankings" && r.status === 200).at(-1)!.payload as RankingResponse;
  const row = ranking.rows.find(r => r.asset === "BTC")!;
  expect(row.state).toBe("ready");
  await expect(page.locator('[data-asset="BTC"] td').nth(2)).toHaveText(formatPrice(row.referenceClose.value));
  await expect(page.locator('[data-asset="BTC"] td').nth(3)).toContainText(formatPriceChange(row.returnPct!));
  await expect(page.getByTestId("selected-metrics")).toContainText(indicatorLabel(row.turnoverRatio, "倍"));
  await openReferenceNotes(page);
  await page.getByLabel("保存先の取扱い契約").selectOption("bitget:BTCUSDT");
  const noteText = `P01 ${info.project.name} ${Date.now()} 実データを照合。参照と取扱い契約を区別。`;
  await page.getByLabel("理由", { exact: true }).fill("実数値の比較確認");
  await page.getByLabel("短い観測メモ").fill(noteText);
  await page.getByLabel("保存時の指標を添付する").check();
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === "/api/market-past-notes" && r.request().method() === "POST");
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  expect((await saved).ok()).toBe(true);
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  const favorite = page.getByRole("button", { name: "BTCをお気に入り登録", exact: true });
  if (await favorite.count()) await favorite.click();
  await expect(page.getByRole("button", { name: "BTCをお気に入り解除" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("表示名", { exact: true }).fill(`実比較 ${info.project.name}`);
  await page.getByRole("button", { name: "表示条件を保存", exact: true }).click();
  await expect(page.getByLabel("保存した表示", { exact: true }).locator("option")).toContainText(["選択してください", `実比較 ${info.project.name}`]);
  const nativeLink = page.getByRole("link", { name: "bitget · BTCUSDT のnative詳細" });
  await nativeLink.scrollIntoViewIfNeeded();
  await expect(nativeLink).toBeInViewport();
  await nativeLink.click();
  await expect(page).toHaveURL(/mode=native/);
  await expect(page.getByRole("region", { name: "価格・出来高" })).toContainText("bitget:BTCUSDT");
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "参照市場へ戻る" }).click();
  await expect(selected).toHaveAttribute("aria-pressed", "true");
  await expect(selected).toBeFocused();
  await page.reload();
  await expect(page.getByRole("button", { name: "BTCをお気に入り解除" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("保存した表示", { exact: true }).selectOption({ label: `実比較 ${info.project.name}` });
  await selected.click();
  await openReferenceNotes(page);
  await page.getByLabel("保存先の取扱い契約").selectOption("bitget:BTCUSDT");
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  // The live adopted PEPE mapping contains an obsolete Bitget version.
  const pepe = page.locator('[data-testid="ranking-row"][data-asset="PEPE"] .select-row');
  await pepe.focus();
  await pepe.press("Enter");
  await expect(page.getByRole("heading", { name: "PEPE", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "bitget · PEPEUSDT のnative詳細" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "aster · 1000PEPEUSDT のnative詳細" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await evidence.flush();
  expect(evidence.errors).toEqual([]);
  expect(evidence.writes.length).toBeGreaterThan(0);
  await info.attach("actual-data-browser", { body: JSON.stringify(evidence, null, 2), contentType: "application/json" });
});

test("P02 実nativeの3Venue・指標・取得元を確認し保存と次銘柄を操作", async ({ page }, info) => {
  const evidence = await record(page);
  await page.goto("/?mode=native");
  await page.getByLabel("検索", { exact: true }).fill("BTC");
  const snapshots: unknown[] = [];
  for (const venue of ["bitget", "hyperliquid", "aster"]) {
    const choice = page.getByRole("button", { name: `BTC ${venue}を詳細表示`, exact: true });
    await choice.focus();
    await choice.press("Enter");
    await expect(page.getByRole("heading", { name: "BTC PERP", exact: true })).toBeVisible();
    await page.getByText(/^取得元・品質/).click();
    await expect(page.getByRole("region", { name: "契約・取得元" })).toContainText(venue);
    const bundle = await (await page.request.get("/api/market-data")).json() as MarketArtifactBundle;
    const instrument = bundle.universe.items.find(i => i.venue === venue && i.baseAsset === "BTC")!;
    const metricsResponse = await page.request.get("/api/market-metrics");
    expect(metricsResponse.ok()).toBe(true);
    const metrics = await metricsResponse.json() as MarketMetricsArtifact;
    const metric = metrics.rows.find(m => m.venueInstrumentId === instrument.venueInstrumentId && m.venueInstrumentVersionId === instrument.venueInstrumentVersionId)!;
    expect(metric).toBeTruthy();
    await expect(page.getByRole("region", { name: "契約・取得元" })).toContainText(`${instrument.venueInstrumentId} · version ${instrument.venueInstrumentVersionId}`);
    const changes = page.getByRole("region", { name: "追加の市場変化指標" });
    for (const window of ["15m", "1h", "24h"]) {
      const value = metric.tradeChange[window];
      if (value.availability === "available") {
        expect(value.value).toBeCloseTo(100 * (value.endValue! / value.startValue! - 1), 10);
        await expect(changes).toContainText(formatPriceChange(value.value!));
      } else {
        expect(value.value).toBeNull();
      }
    }
    snapshots.push({ instrument, metric, browserObservedAt: new Date().toISOString() });
    await info.attach(`${venue}-screen`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    await page.getByText(/^取得元・品質/).click();
  }
  const btc = page.getByRole("button", { name: "BTC bitgetを詳細表示", exact: true });
  await btc.click();
  const noteText = `P02 ${info.project.name} ${Date.now()} 3取引所の取得元と欠測を確認。`;
  await page.getByLabel("理由", { exact: true }).fill("native実データの確認");
  await page.getByLabel("短い観測メモ").fill(noteText);
  await page.getByRole("button", { name: "注記を保存", exact: true }).click();
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  await page.getByLabel("検索", { exact: true }).clear();
  await page.getByRole("button", { name: "ETH bitgetを詳細表示", exact: true }).click();
  await expect(page.getByText(noteText, { exact: true })).toHaveCount(0);
  await btc.click();
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  await page.reload();
  await btc.click();
  await expect(page.getByText(noteText, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await evidence.flush();
  expect(evidence.errors).toEqual([]);
  await info.attach("native-real-endpoints", { body: JSON.stringify({ snapshots, ...evidence }, null, 2), contentType: "application/json" });
});

// Run this separately with -g P03 after the P01/P02 preview has stopped. A new
// preview process and browser context must read the same isolated persisted state.
test("P03 候補Web再起動後にお気に入り・表示条件・保存メモを復帰", async ({ page }, info) => {
  const captured = JSON.parse(await readFile(resolve(process.env.PREP_WATCHDECK_PERSONA_STATE_DIR!,
    "../persistence-before-restart.json"), "utf-8")) as { notes: MarketPastNote[]; workspace: UserWorkspace };
  expect(captured.notes.length, "saved notes must exist before restart").toBeGreaterThan(0);
  expect((await page.request.get("/api/market-data")).ok(), "live artifact mirror must remain active").toBe(true);
  await page.goto("/?mode=reference", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "BTCをお気に入り解除" })).toHaveAttribute("aria-pressed", "true");
  await page.getByLabel("保存した表示", { exact: true }).selectOption({ label: `実比較 ${info.project.name}` });
  await page.locator('[data-testid="ranking-row"][data-asset="BTC"] .select-row').press("Enter");
  await openReferenceNotes(page);
  await page.getByLabel("保存先の取扱い契約").selectOption("bitget:BTCUSDT");
  for (const note of captured.notes) {
    await expect(page.locator(".note-list")).toContainText(note.note);
  }
  const restored = await (await page.request.get("/api/market-past-notes?venueInstrumentId=bitget%3ABTCUSDT")).json();
  expect(restored.notes).toEqual(captured.notes);
  expect(await (await page.request.get("/api/user-workspace")).json()).toEqual(captured.workspace);
  await info.attach("restart-restored", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
});
