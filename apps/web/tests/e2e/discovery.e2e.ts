import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MarketArtifactBundle } from "../../src/lib/server/market-artifact-repository";
import type { UniverseInstrumentArtifact } from "../../src/lib/generated/universe-snapshot";
import type { UserWorkspace } from "../../src/lib/server/user-workspace-repository";
import type { DecisionHistory } from "../../src/lib/market/decisions";
import { discoveryFixture } from "../../src/lib/discovery/discovery-test-fixture";
import { rankingFixture } from "../../src/lib/market/ranking-test-fixture";

function marketBundle(now: number): MarketArtifactBundle {
  const generatedAt = new Date(now).toISOString();
  const item = { venueInstrumentId: "bitget:BTCUSDT", venueInstrumentVersionId: 1,
    venue: "bitget", sourceSymbol: "BTCUSDT", baseAsset: "BTC", groupId: "crypto:BTC:linear-perp",
    mappingMethod: "exact_base_heuristic", quoteAsset: "USDT", settleAsset: "USDT", collateralAsset: "USDT",
    active: true, marketType: "linear_perpetual", executionModel: "clob",
    catalog: { sourceKind: "native_rest", endpoint: "/fixture", documentationUrl: null, payloadHash: "fixture", observedAt: generatedAt, sourceAt: null },
    quality: "ready", qualityReasons: [], ageSeconds: 0, collectorRunId: "fixture", cycleAt: generatedAt,
    observedAt: generatedAt, sourceAt: generatedAt, sourcePayloadHash: "fixture", errorCode: null,
    markPrice: 101, referencePrice: 101, referencePriceKind: "index", bestBid: 100, bestAsk: 102,
    fundingRateRaw: .0001, fundingIntervalSeconds: 28800, fundingRatePerHour: .0000125, nextFundingAt: generatedAt,
    openInterestRaw: 10, openInterestRawUnit: "base", openInterestBase: 10, openInterestNotional: 1010,
    volume24hRaw: 1000000, volume24hUnit: "quote", referenceMarkMedian: { status: "unavailable", value: null,
      venueCount: 1, venues: ["bitget"], cycleAt: generatedAt, maxAgeSeconds: 1, skewSeconds: 0,
      unavailableReason: "insufficient_venues", parityAssumptionCode: "usd_usdc_usdt_reference_only" }
  } as UniverseInstrumentArtifact;
  return {
    universe: { schemaVersion: 1, generatedAt, status: "ready", qualityReasons: [],
      parityAssumption: { code: "usd_usdc_usdt_reference_only", appliedTo: "reference_mark_median_only", statement: "Fixture" }, items: [item] },
    chart: { schemaVersion: 1, generatedAt, status: "unavailable", qualityReasons: [], venueInstrumentId: null, timeframes: [] },
    selected: { schemaVersion: 1, generatedAt, status: "unavailable", qualityReasons: [], selection: null,
      disclaimers: { includesFees: false, predictsFutureImpact: false, confirmsOrderAvailability: false, statement: "Fixture" } },
    service: { schemaVersion: 1, generatedAt, status: "ready", qualityReasons: [], collectors: [],
      catalog: { status: "ready", latestAt: generatedAt, ageSeconds: 0, maxAgeSeconds: 1800, errorCode: null },
      l1: { status: "ready", latestAt: generatedAt, ageSeconds: 0, maxAgeSeconds: 120, errorCode: null },
      artifacts: ["universe-snapshot.json", "market-chart.json", "selected-market.json"].map(name => ({ name, status: "ready", generatedAt, errorCode: null })) }
  };
}

test("候補4件を解除・再読込後も保持し、判断根拠を固定して明示確認でのみ実Venueへ移る", async ({ page }, testInfo) => {
  let now = Date.now();
  await page.clock.install({ time: new Date(now) });
  let source = discoveryFixture(now);
  let workspace: UserWorkspace = { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] };
  let history: DecisionHistory = { schemaVersion: 1, revision: 0, decisions: [] };
  let selected = "bitget:ETHUSDT";
  const selectionPosts: unknown[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", cause => pageErrors.push(cause.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams, source.rankingCutoff!) }));
  await page.route("**/api/discovery?**", route => {
    const ids = new URL(route.request().url()).searchParams.getAll("assetId");
    return route.fulfill({ json: { ...source, rows: ids.length ? source.rows.filter(row => ids.includes(row.assetId)) : source.rows } });
  });
  await page.route("**/api/user-workspace", route => {
    if (route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      expect(command.action).toBe("setPin");
      if (command.enabled && workspace.pins.length === 4) return route.fulfill({ status: 413, json: { error: "workspace_limit" } });
      workspace = { ...workspace, revision: workspace.revision + 1, pins: command.enabled ? [...workspace.pins, command.pin]
        : workspace.pins.filter(pin => pin.target.id !== command.pin.target.id) };
    }
    return route.fulfill({ json: workspace });
  });
  await page.route("**/api/decisions", route => {
    if (route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      history = { ...history, revision: history.revision + 1,
        decisions: [...history.decisions, { ...command.decision, recordedAt: new Date(now).toISOString() }] };
    }
    return route.fulfill({ json: history });
  });
  await page.route("**/api/market-data", route => route.fulfill({ json: marketBundle(now) }));
  await page.route("**/api/selection", route => {
    const command = route.request().postDataJSON(); selectionPosts.push(command);
    selected = command.venueInstrumentId;
    return route.fulfill({ json: { ok: true, command: { requestedAt: new Date(now).toISOString() } } });
  });
  for (const path of ["chart-history?**", "price-change?**", "market-metrics", "candle-recovery", "candle-audits"]) {
    await page.route(`**/api/${path}`, route => route.fulfill({ status: 503, json: { error: "fixture_unavailable" } }));
  }
  await page.goto("/?mode=reference");
  const panel = page.getByTestId("discovery-workflow");
  await expect(panel).toContainText("固定監視: 15分");
  for (const asset of ["BTC", "ETH", "SOL", "MISSING"]) {
    await panel.getByRole("button", { name: new RegExp(`^${asset} ·`) }).click();
    await expect(panel.locator(`[data-target="asset:${asset}"]`)).toBeVisible();
  }
  await panel.getByRole("button", { name: /^NOCHART ·/ }).click();
  await expect(panel.getByRole("alert")).toContainText("最大4件");
  expect(selectionPosts).toHaveLength(0); expect(selected).toBe("bitget:ETHUSDT");
  source.rows.forEach(row => { row.state = "not_matched"; row.confirmation = null; });
  const sol = source.rows.find(row => row.asset === "SOL")!;
  sol.episodeId = null; sol.direction = "turnover";
  now += 15000; await page.clock.fastForward(15000);
  await expect(panel.getByTestId("comparison-card")).toHaveCount(4);
  await expect(panel.locator('[data-target="asset:BTC"]')).toContainText("条件解除");
  await expect(panel.locator('[data-target="asset:SOL"]')).toContainText("条件未成立 · 価格方向 ±2% 内");
  await page.reload();
  await expect(panel.getByTestId("comparison-card")).toHaveCount(4);
  const btc = panel.locator('[data-target="asset:BTC"]');
  await btc.getByRole("button", { name: "この成立を見送り" }).click();
  await panel.getByLabel("判断理由").fill("板が薄いので見送り");
  const oldClose = source.rows.find(row => row.asset === "BTC")!.raw.referenceClose.value;
  source.rows.find(row => row.asset === "BTC")!.raw.referenceClose.value = 105;
  now += 15000; await page.clock.fastForward(15000);
  await panel.getByRole("button", { name: "判断を保存", exact: true }).click();
  expect((history.decisions[0].snapshot.row as typeof source.rows[0]).raw.referenceClose.value).toBe(oldClose);
  await expect(btc).toContainText("この成立は見送り済み");
  source.rows.find(row => row.asset === "BTC")!.state = "matched";
  source.rows.find(row => row.asset === "BTC")!.episodeId = "episode-BTC-2";
  now += 15000; await page.clock.fastForward(15000);
  await expect(panel.getByRole("button", { name: /^BTC ·/ })).toBeVisible();
  expect(selectionPosts).toHaveLength(0);
  source.rows.find(row => row.asset === "BTC")!.originals[0].versionId = 2;
  source.rows.find(row => row.asset === "BTC")!.native[0].versionId = 2;
  now += 15000; await page.clock.fastForward(15000);
  await expect(btc).toContainText("要再確認");
  expect(workspace.pins[0].target.kind === "reference" && workspace.pins[0].target.originals).toEqual(["bitget:BTCUSDT:1"]);
  source.rows.find(row => row.asset === "BTC")!.originals[0].versionId = 1;
  source.rows.find(row => row.asset === "BTC")!.native[0].versionId = 1;
  now += 15000; await page.clock.fastForward(15000);
  await btc.locator("summary").filter({ hasText: "実Venue:" }).click();
  await btc.getByRole("button", { name: "この実Venueを確認" }).click();
  expect(selectionPosts).toHaveLength(0);
  const bundle = marketBundle(Date.now());
  const runtime = resolve(process.cwd(), "../../var/tmp/e2e/runtime/artifacts");
  await mkdir(runtime, { recursive: true });
  for (const [name, payload] of Object.entries({ "universe-snapshot": bundle.universe, "market-chart": bundle.chart,
    "selected-market": bundle.selected, "service-state": bundle.service })) {
    await writeFile(resolve(runtime, `${name}.json`), JSON.stringify(payload));
  }
  await panel.getByRole("button", { name: "確認して実Venueへ移動" }).click();
  await expect(page).toHaveURL(/mode=native.*instrument=bitget%3ABTCUSDT/);
  await expect(page.getByRole("heading", { name: "取引所別", exact: true })).toBeVisible();
  await expect.poll(() => selectionPosts.length).toBeGreaterThan(0);
  expect(selected).toBe("bitget:BTCUSDT");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("discovery-confirmed-native.png") });
  expect(pageErrors).toEqual([]);
});

test("旧Attentionの候補APIが未対応でもMarketsのランキングを利用できる", async ({ page }) => {
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/discovery?**", route => route.fulfill({ status: 503, json: { error: "discovery_unavailable" } }));
  await page.route("**/api/user-workspace", route => route.fulfill({ json: { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] } }));
  await page.route("**/api/decisions", route => route.fulfill({ json: { schemaVersion: 1, revision: 0, decisions: [] } }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams) }));
  await page.goto("/");
  await expect(page.getByTestId("discovery-workflow")).toContainText("候補機能を利用できません");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
});
