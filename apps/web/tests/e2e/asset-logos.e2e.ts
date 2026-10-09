import { readFileSync } from "node:fs";
import { mkdir, rm, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import type { RankedRow } from "../../src/lib/generated/ranking-response";
import type { UniverseInstrumentArtifact } from "../../src/lib/generated/universe-snapshot";
import type { MarketArtifactBundle } from "../../src/lib/server/market-artifact-repository";
import type { FavoriteTarget, UserWorkspace } from "../../src/lib/server/user-workspace-repository";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

type Original = RankedRow["originals"][number];
type LogoFixtureRow = { id: string; asset: string; originals: Original[] };
// Contract snapshot reviewed for the logo bindings' map c1381b1848be8f107fcacfea.
// Current ranking-map revisions are separate identities and may correctly have no reviewed logo.
const reviewedLogoFixtures: LogoFixtureRow[] = [
  { id: "crypto:BTC", asset: "BTC", originals: [
    { venue: "aster", instrumentId: "aster:BTCUSDT", versionId: 640, symbol: "BTCUSDT", baseAsset: "BTC", multiplier: 1 },
    { venue: "bitget", instrumentId: "bitget:BTCUSDT", versionId: 1, symbol: "BTCUSDT", baseAsset: "BTC", multiplier: 1 },
    { venue: "hyperliquid", instrumentId: "hyperliquid:BTC", versionId: 463, symbol: "BTC", baseAsset: "BTC", multiplier: 1 }
  ] },
  { id: "crypto:ETH", asset: "ETH", originals: [
    { venue: "aster", instrumentId: "aster:ETHUSDT", versionId: 641, symbol: "ETHUSDT", baseAsset: "ETH", multiplier: 1 },
    { venue: "bitget", instrumentId: "bitget:ETHUSDT", versionId: 2, symbol: "ETHUSDT", baseAsset: "ETH", multiplier: 1 },
    { venue: "hyperliquid", instrumentId: "hyperliquid:ETH", versionId: 464, symbol: "ETH", baseAsset: "ETH", multiplier: 1 }
  ] },
  { id: "crypto:SOL", asset: "SOL", originals: [
    { venue: "aster", instrumentId: "aster:SOLUSDT", versionId: 643, symbol: "SOLUSDT", baseAsset: "SOL", multiplier: 1 },
    { venue: "bitget", instrumentId: "bitget:SOLUSDT", versionId: 7643, symbol: "SOLUSDT", baseAsset: "SOL", multiplier: 1 },
    { venue: "hyperliquid", instrumentId: "hyperliquid:SOL", versionId: 467, symbol: "SOL", baseAsset: "SOL", multiplier: 1 }
  ] },
  { id: "crypto:SHIB", asset: "SHIB", originals: [
    { venue: "aster", instrumentId: "aster:1000SHIBUSDT", versionId: 650, symbol: "1000SHIBUSDT", baseAsset: "1000SHIB", multiplier: 1000 },
    { venue: "bitget", instrumentId: "bitget:SHIBUSDT", versionId: 26, symbol: "SHIBUSDT", baseAsset: "SHIB", multiplier: 1 },
    { venue: "hyperliquid", instrumentId: "hyperliquid:kSHIB", versionId: 493, symbol: "kSHIB", baseAsset: "kSHIB", multiplier: 1000 }
  ] }
];
const unreviewedLogoOriginal: Original = {
  venue: "aster", instrumentId: "aster:AIUSDT", versionId: 9538, symbol: "AIUSDT", baseAsset: "AI", multiplier: 1
};
const logoManifest = JSON.parse(readFileSync(resolve(process.cwd(), "src/lib/assets/asset-logos.json"), "utf8")) as { logos: { path: string }[] };
const runtimeRoot = resolve(process.cwd(), "../../var/tmp/e2e/runtime");
const errors = new WeakMap<Page, string[]>();

function reviewedLogoFixture(asset: string): LogoFixtureRow {
  const row = reviewedLogoFixtures.find(entry => entry.asset === asset);
  if (!row) throw new Error(`Missing reviewed fixture identity: ${asset}`);
  return row;
}

function nativeInstrument(original: Original, generatedAt: string): UniverseInstrumentArtifact {
  return {
    venueInstrumentId: original.instrumentId, venueInstrumentVersionId: original.versionId,
    venue: original.venue, sourceSymbol: original.symbol, baseAsset: original.baseAsset,
    groupId: `crypto:${original.baseAsset}:linear-perp`, mappingMethod: "exact_base_heuristic",
    quoteAsset: "USDT", settleAsset: "USDT", collateralAsset: "USDT", active: true,
    marketType: "linear_perpetual", executionModel: "clob",
    catalog: { sourceKind: "native_rest", endpoint: "/e2e/catalog", documentationUrl: null,
      payloadHash: "fixture-catalog", observedAt: generatedAt, sourceAt: null },
    quality: "ready", qualityReasons: [], ageSeconds: 1, collectorRunId: "fixture-run",
    cycleAt: generatedAt, observedAt: generatedAt, sourceAt: null, sourcePayloadHash: "fixture-l1",
    errorCode: null, markPrice: 65000, referencePrice: 65001, referencePriceKind: "index",
    bestBid: 64999, bestAsk: 65001, fundingRateRaw: 0.0001, fundingIntervalSeconds: 28800,
    fundingRatePerHour: 0.0000125, nextFundingAt: generatedAt,
    openInterestRaw: 10, openInterestRawUnit: "base", openInterestBase: 10,
    openInterestNotional: 650000, volume24hRaw: 6500000, volume24hUnit: "quote",
    referenceMarkMedian: { status: "unavailable", value: null, venueCount: 1,
      venues: [original.venue], cycleAt: generatedAt, maxAgeSeconds: 1, skewSeconds: 0,
      unavailableReason: "insufficient_venues", parityAssumptionCode: "usd_usdc_usdt_reference_only" }
  };
}

async function prepare(page: Page, unknownVersion = false) {
  const pageErrors: string[] = [];
  errors.set(page, pageErrors);
  page.on("pageerror", cause => pageErrors.push(cause.message));
  const externalRequests: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.protocol !== "data:" && url.hostname !== "127.0.0.1" && url.hostname !== "s3.tradingview.com") {
      externalRequests.push(request.url());
    }
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    return url.hostname === "127.0.0.1" || url.hostname === "s3.tradingview.com"
      ? route.fallback() : route.abort();
  });
  const generatedAt = new Date().toISOString();
  const btc = reviewedLogoFixture("BTC");
  const originals = btc.originals.filter(entry => entry.venue === "bitget" || entry.venue === "hyperliquid")
    .map(entry => ({ ...entry, versionId: entry.versionId + (unknownVersion ? 900000 : 0) }));
  const shib = reviewedLogoFixture("SHIB").originals.find(entry => entry.venue === "aster")!;
  const ai = unreviewedLogoOriginal;
  const bundle: MarketArtifactBundle = {
    universe: { schemaVersion: 1, generatedAt, status: "ready", qualityReasons: [],
      parityAssumption: { code: "usd_usdc_usdt_reference_only", appliedTo: "reference_mark_median_only",
        statement: "Fixture only" },
      items: [...originals, shib, ai].map(original => nativeInstrument(original, generatedAt)) },
    chart: { schemaVersion: 1, generatedAt, status: "unavailable", qualityReasons: [],
      venueInstrumentId: null, timeframes: [] },
    selected: { schemaVersion: 1, generatedAt, status: "unavailable", qualityReasons: [],
      disclaimers: { includesFees: false, predictsFutureImpact: false, confirmsOrderAvailability: false,
        statement: "Fixture only" }, selection: null },
    service: { schemaVersion: 1, generatedAt, status: "ready", qualityReasons: [], collectors: [],
      catalog: { status: "ready", latestAt: generatedAt, ageSeconds: 1, maxAgeSeconds: 1800, errorCode: null },
      l1: { status: "ready", latestAt: generatedAt, ageSeconds: 1, maxAgeSeconds: 120, errorCode: null },
      artifacts: ["universe-snapshot.json", "market-chart.json", "selected-market.json"].map(name => ({
        name, status: "ready", generatedAt, errorCode: null })) }
  };
  await mkdir(resolve(runtimeRoot, "artifacts"), { recursive: true });
  await Promise.all(Object.entries({ "universe-snapshot": bundle.universe, "market-chart": bundle.chart,
    "selected-market": bundle.selected, "service-state": bundle.service }).map(([name, payload]) =>
    writeFile(resolve(runtimeRoot, "artifacts", `${name}.json`), JSON.stringify(payload))));
  let workspace: UserWorkspace = { schemaVersion: 1, revision: 0, favorites: [], savedViews: [] };
  await page.route("**/api/user-workspace", async route => {
    if (route.request().method() === "POST") {
      const request = route.request().postDataJSON() as { target: FavoriteTarget; enabled: boolean };
      workspace = { ...workspace, revision: workspace.revision + 1,
        favorites: request.enabled ? [...workspace.favorites, request.target]
          : workspace.favorites.filter(entry => entry.id !== request.target.id) };
    }
    await route.fulfill({ json: workspace });
  });
  await page.route("**/api/market-data", route => route.fulfill({ json: bundle }));
  await page.route("**/api/selection", route => route.fulfill({ json: { ok: true,
    command: { requestedAt: generatedAt } } }));
  await page.route("**/api/chart-history?*", route => route.fulfill({ status: 503, json: { error: "fixture_no_history" } }));
  await page.route("**/api/price-change?*", route => route.fulfill({ status: 503, json: { error: "fixture_no_history" } }));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ contentType: "application/javascript", body: "" }));
  await page.route("**/api/rankings?*", async route => {
    const payload = rankingFixture(new URL(route.request().url()).searchParams);
    for (const row of payload.rows) {
      const identity = reviewedLogoFixtures.find(entry => entry.asset === row.asset);
      if (identity) { row.id = identity.id; row.originals = identity.originals; }
      if (row.asset === "BTC" && unknownVersion) row.originals = originals;
    }
    await route.fulfill({ json: payload });
  });
  return { externalRequests, originals };
}

async function showList(page: Page) {
  const back = page.getByRole("button", { name: "一覧へ戻る", exact: true });
  if (await back.isVisible()) await back.click();
}

async function expectLogoFrame(icon: Locator, size: number) {
  await expect(icon).toHaveCSS("width", `${size}px`);
  await expect(icon).toHaveCSS("height", `${size}px`);
  const scaled = await icon.evaluate(element =>
    document.documentElement.dataset.layout === "ultra" &&
    matchMedia("(max-width: 960px)").matches &&
    element.closest(".ranking-page .asset-icon-slot") !== null);
  const displayedSize = scaled ? size * 0.8 : size;
  const box = await icon.boundingBox();
  expect(box?.width).toBeCloseTo(displayedSize, 2);
  expect(box?.height).toBeCloseTo(displayedSize, 2);
}

async function verifiedLogo(icon: Locator, size: number, assetId = "crypto:BTC") {
  await expect(icon).toHaveAttribute("data-logo-state", "verified");
  await expect(icon).toHaveAttribute("data-asset-id", assetId);
  await expect(icon).toHaveAttribute("aria-hidden", "true");
  const image = icon.locator("img");
  await expect(image).toHaveAttribute("alt", "");
  await expect.poll(() => image.evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  const src = await image.getAttribute("src");
  expect(src).toMatch(/^\/asset-logos\//);
  await expectLogoFrame(icon, size);
  return src;
}

test.afterEach(async ({ page }) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.close();
  await rm(runtimeRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  expect(errors.get(page) ?? [], "ブラウザの未処理例外").toEqual([]);
});

test("確認済みロゴはランキング・詳細・取引所別・お気に入りで同じ資産を示す", async ({ page }, testInfo) => {
  const probe = await prepare(page);
  await page.goto("/rankings?includeUnranked=1");
  const row = page.locator('[data-testid="ranking-row"][data-asset="BTC"]');
  await expect(row).toBeVisible();
  const logo = await verifiedLogo(row.getByTestId("asset-icon"), 22);
  for (const asset of ["ETH", "SOL"]) {
    const addedRow = page.locator(`[data-testid="ranking-row"][data-asset="${asset}"]`);
    expect(await verifiedLogo(addedRow.getByTestId("asset-icon"), 22, `crypto:${asset}`)).not.toBe(logo);
  }
  await expect(row.locator(".select-row")).toContainText("BTC");
  const missing = page.locator('[data-testid="ranking-row"][data-asset="MISSING"]');
  await expect(missing.getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await expect(missing.getByTestId("asset-icon").locator("img")).toHaveCount(0);
  const favorite = row.getByRole("button", { name: "BTCをお気に入り登録", exact: true });
  await favorite.filter({ visible: true }).click();
  await page.getByLabel("お気に入りのみ", { exact: true }).check();
  await expect(page.getByTestId("ranking-row")).toHaveCount(1);
  expect(await verifiedLogo(row.getByTestId("asset-icon"), 22)).toBe(logo);
  await row.locator(".select-row").click();
  expect(await verifiedLogo(page.locator(".selected-heading").getByTestId("asset-icon"), 32)).toBe(logo);
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Bitget · BTCUSDT を確認", exact: true }).click();
  expect(await verifiedLogo(page.locator(".instrument-heading").getByTestId("asset-icon"), 32)).toBe(logo);
  await expect(page.locator(".instrument-heading")).toContainText("BTCUSDT");
  await expect(page.getByLabel("選択契約のデータ元")).toContainText("Bitget");
  await showList(page);
  const native = page.locator('button.instrument-select[data-instrument-id="bitget:BTCUSDT"]');
  expect(await verifiedLogo(native.getByTestId("asset-icon"), 22)).toBe(logo);
  expect(await verifiedLogo(page.locator('button.instrument-select[data-instrument-id="hyperliquid:BTC"]').getByTestId("asset-icon"), 22)).toBe(logo);
  await expect(page.locator('button.instrument-select[data-instrument-id="aster:AIUSDT"]').getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await expect(page.locator('button.instrument-select[data-instrument-id="aster:1000SHIBUSDT"]')).toContainText("1000SHIB");
  await expect(page.locator('button.instrument-select[data-instrument-id="aster:1000SHIBUSDT"]')).toContainText("aster · 1000SHIBUSDT");
  await verifiedLogo(page.locator('button.instrument-select[data-instrument-id="aster:1000SHIBUSDT"]').getByTestId("asset-icon"), 22, "crypto:SHIB");
  await page.getByRole("button", { name: "BTC bitgetをお気に入り登録", exact: true }).click();
  await page.getByLabel("お気に入りのみ", { exact: true }).check();
  await expect(page.locator("button.instrument-select")).toHaveCount(1);
  expect(await verifiedLogo(native.getByTestId("asset-icon"), 22)).toBe(logo);
  expect(probe.externalRequests).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.goto("/asset-logos/credits.html");
  const images = page.locator("main img");
  await expect(images).toHaveCount(logoManifest.logos.length);
  // Decode every actual local image, including those outside the ranking fixture.
  await images.evaluateAll(elements => Promise.all(elements.map(element => (element as HTMLImageElement).decode())));
  expect(await images.evaluateAll(elements => elements.every(element => (element as HTMLImageElement).naturalWidth > 0))).toBe(true);
  const paths = await images.evaluateAll(elements => elements.map(element => element.getAttribute("src")));
  expect(paths.sort()).toEqual(logoManifest.logos.map(entry => entry.path).sort());
  await expect(page.getByText("MIT License 全文", { exact: true })).toBeVisible();
  for (const colorScheme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`asset-logos-${colorScheme}.png`), fullPage: true });
  }
  expect(probe.externalRequests).toEqual([]);
});

async function geometry(row: Locator) {
  const frame = await row.getByTestId("asset-icon").boundingBox();
  const bounds = await row.boundingBox();
  const change = await row.locator("td.numeric.change").boundingBox();
  const turnover = await row.locator("td.turnover").boundingBox();
  expect(frame).not.toBeNull(); expect(bounds).not.toBeNull();
  expect(change).not.toBeNull(); expect(turnover).not.toBeNull();
  return { frame, bounds, change, turnover };
}

test("ロゴの404でも行と数値の位置が変わらず選択できる", async ({ page }, testInfo) => {
  const probe = await prepare(page);
  await page.goto("/rankings");
  const row = page.locator('[data-testid="ranking-row"][data-asset="BTC"]');
  const icon = row.getByTestId("asset-icon");
  const logo = await verifiedLogo(icon, 22);
  await page.evaluate(() => document.fonts.ready);
  const before = await geometry(row);
  await page.route(`**${logo}*`, route => route.fulfill({ status: 404, body: "" }));
  await page.reload();
  await expect(icon).toHaveAttribute("data-logo-state", "fallback");
  await expect(icon).not.toHaveAttribute("data-asset-id", /.+/);
  await expect(icon.locator("img")).toHaveCount(0);
  await expect(row.locator(".select-row")).toContainText("BTC");
  const after = await geometry(row);
  expect(after).toEqual(before);
  await expectLogoFrame(icon, 22);
  const viewport = page.viewportSize()!;
  for (const numeric of [after.change!, after.turnover!]) {
    expect(numeric.x).toBeGreaterThanOrEqual(0);
    expect(numeric.x + numeric.width).toBeLessThanOrEqual(viewport.width);
  }
  await row.locator(".select-row").click();
  const detailIcon = page.locator(".selected-heading").getByTestId("asset-icon");
  await expect(detailIcon).toHaveAttribute("data-logo-state", "fallback");
  const detailFrame = await detailIcon.boundingBox();
  expect(detailFrame?.width).toBe(32); expect(detailFrame?.height).toBe(32);
  await expect(page.getByRole("heading", { name: "BTC", exact: true })).toBeVisible();
  await expect(page.getByTestId("selected-primary-metrics")).toContainText("500,000");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(probe.externalRequests).toEqual([]);
  const evidence = testInfo.outputPath("asset-logo-404-layout.json");
  await writeFile(evidence, JSON.stringify({ viewport, before, after, detailFrame, externalRequests: probe.externalRequests }, null, 2));
  await testInfo.attach("asset-logo-404-layout.json", { path: evidence, contentType: "application/json" });
  const screenshot = testInfo.outputPath("asset-logo-404-detail.png");
  await page.screenshot({ path: screenshot });
  await testInfo.attach("asset-logo-404-detail.png", { path: screenshot, contentType: "image/png" });
});

test("同じシンボルでも未確認の契約版には実ロゴを割り当てない", async ({ page }) => {
  const probe = await prepare(page, true);
  await page.goto("/rankings");
  const row = page.locator('[data-testid="ranking-row"][data-asset="BTC"]');
  await expect(row.getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await expect(row.getByTestId("asset-icon").locator("img")).toHaveCount(0);
  await expect(row.locator(".select-row")).toContainText("BTC");
  await row.locator(".select-row").click();
  await expect(page.locator(".selected-heading").getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await page.goto("/?mode=native");
  await showList(page);
  const native = page.locator('button.instrument-select[data-instrument-id="bitget:BTCUSDT"]');
  await expect(native.getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await expect(native.getByTestId("asset-icon").locator("img")).toHaveCount(0);
  await expect(native).toContainText("bitget · BTCUSDT");
  await native.click();
  await expect(page.locator(".instrument-heading").getByTestId("asset-icon")).toHaveAttribute("data-logo-state", "fallback");
  await expect(page.locator(".instrument-heading")).toContainText("BTCUSDT");
  expect(probe.externalRequests).toEqual([]);
});
