import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import type { MarketArtifactBundle } from "../../src/lib/server/market-artifact-repository";
import type { UniverseInstrumentArtifact } from "../../src/lib/generated/universe-snapshot";
import type { UserWorkspace } from "../../src/lib/server/user-workspace-repository";
import type { DecisionHistory } from "../../src/lib/market/decisions";
import { discoveryFixture, discoverySummaryFixture } from "../../src/lib/discovery/discovery-test-fixture";
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

async function storedComparison(page: Page) {
  const now = Math.floor(Date.now() / 60_000) * 60_000 + 10_000;
  await page.clock.install({ time: new Date(now) });
  const state = {
    source: discoveryFixture(now),
    workspace: { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] } as UserWorkspace,
    history: { schemaVersion: 1, revision: 0, decisions: [] } as DecisionHistory,
    historyUnavailable: false,
    decisionResponseLost: false,
    decisions: [] as { decision: DecisionHistory["decisions"][number]; expectedRevision: number }[],
    selectionPosts: [] as unknown[]
  };
  state.workspace.pins = state.source.rows.filter(row => ["BTC", "ETH"].includes(row.asset))
    .map(row => ({ target: { kind: "reference", id: row.assetId, referenceKey: row.referenceKey!,
      originals: row.originals.map(original => `${original.instrumentId}:${original.versionId}`) },
      episodeId: row.episodeId, discoveredAt: row.raw.decisionAt,
      snapshot: { asset: row.asset, referenceClose: row.raw.referenceClose } }));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams, state.source.rankingCutoff!) }));
  await page.route("**/api/discovery-summary", route => route.fulfill({ json: {
    schemaVersion: "discovery-summary-v1", policy: state.source.policy, generationId: state.source.generationId,
    decisionAt: state.source.decisionAt, rankingCutoff: state.source.rankingCutoff, status: state.source.status,
    reason: state.source.reason, historyAvailableFrom: state.source.historyAvailableFrom,
    rows: state.source.rows.map(({ raw: _raw, native: _native, turnoverComparison: _comparison, ...row }) => row)
  } }));
  await page.route("**/api/discovery?**", route => {
    const ids = new URL(route.request().url()).searchParams.getAll("assetId");
    return route.fulfill({ json: { ...state.source, rows: state.source.rows.filter(row => ids.includes(row.assetId)) } });
  });
  await page.route("**/api/user-workspace", route => {
    if (route.request().method() === "POST") {
      const command = route.request().postDataJSON();
      state.workspace = { ...state.workspace, revision: state.workspace.revision + 1,
        pins: command.enabled ? [...state.workspace.pins, command.pin]
          : state.workspace.pins.filter(pin => pin.target.id !== command.pin.target.id) };
    }
    return route.fulfill({ json: state.workspace });
  });
  await page.route("**/api/decisions", route => {
    if (route.request().method() === "GET") return route.fulfill(state.historyUnavailable
      ? { status: 500, json: { error: "decision_unavailable" } } : { json: state.history });
    const command = route.request().postDataJSON();
    state.decisions.push(command);
    if (state.decisionResponseLost) {
      state.decisionResponseLost = false;
      return route.fulfill({ status: 500, json: { error: "decision_unavailable" } });
    }
    const saved = state.history.decisions.find(item => item.id === command.decision.id);
    if (saved) {
      const { recordedAt: _recordedAt, ...input } = saved;
      if (JSON.stringify(input) !== JSON.stringify(command.decision)) {
        return route.fulfill({ status: 409, json: { error: "decision_id_conflict" } });
      }
    } else {
      state.history = { ...state.history, revision: state.history.revision + 1,
        decisions: [...state.history.decisions, { ...command.decision, recordedAt: new Date(now).toISOString() }] };
    }
    return route.fulfill({ json: state.history });
  });
  await page.route("**/api/selection", route => {
    state.selectionPosts.push(route.request().postDataJSON());
    return route.fulfill({ json: { ok: true } });
  });
  return state;
}

test("条件判定の件数は全対象を含め、確認不能を成立なしに数えず、古い観測を明示する", async ({ page }) => {
  const state = await storedComparison(page);
  state.source.status = "partial";
  state.source.reason = "incomplete_discovery_coverage";
  state.workspace.pins = [];
  state.source.rows[1].state = "not_matched";
  for (const [index, reason] of [[2, "identity_ineligible"], [3, "comparison_unavailable"], [4, "future_reason"]] as const) {
    state.source.rows[index].state = "unknown";
    state.source.rows[index].reason = reason;
  }
  await page.goto("/?mode=reference");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  await panel.locator("summary").filter({ hasText: "固定監視の条件・取得状況" }).click();
  const coverage = panel.getByRole("region", { name: "固定条件の判定状況" });
  await expect(coverage).toContainText("条件判定済み 2 / 5");
  await expect(coverage).toContainText("成立 1 · 不成立 1");
  await expect(coverage).toContainText("対象確認待ち 1");
  await expect(coverage).toContainText("比較値確認不能 1");
  await expect(coverage).toContainText("その他の確認待ち 1");
  await expect(panel.getByRole("button", { name: /^BTC ·/ })).toBeEnabled();
  await expect(panel.getByRole("button", { name: /^SOL ·/ })).toHaveCount(0);
  await page.clock.fastForward(180_000);
  await expect(coverage).toContainText("前回観測");
  await expect(panel).toContainText("候補データが古くなっています");
  expect(state.decisions).toHaveLength(0);
  expect(state.selectionPosts).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("判断履歴だけが失敗しても比較候補を表示・追加でき、失敗側の再取得で判断を回復する", async ({ page }) => {
  const state = await storedComparison(page);
  state.historyUnavailable = true;
  await page.goto("/?mode=reference");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  await expect(panel.getByTestId("comparison-card")).toHaveCount(2);
  await expect(panel).toContainText("見送り適用は未確認");
  await expect(panel.getByTestId("manual-history")).toContainText("判断履歴 (未確認)");
  await expect(panel.locator('[data-target="asset:BTC"]').getByRole("button", { name: "監視を記録" })).toBeDisabled();
  await panel.getByRole("button", { name: /^SOL ·/ }).click();
  await expect(panel.getByTestId("comparison-card")).toHaveCount(3);
  await expect(panel).toContainText("見送り適用は未確認");
  state.historyUnavailable = false;
  await panel.getByRole("button", { name: "判断履歴を再取得" }).click();
  await expect(panel.locator('[data-target="asset:BTC"]').getByRole("button", { name: "監視を記録" })).toBeEnabled();
  await expect(panel).not.toContainText("見送り適用は未確認");
  expect(state.workspace.pins.map(pin => pin.target.id)).toEqual(["asset:BTC", "asset:ETH", "asset:SOL"]);
  expect(state.decisions).toHaveLength(0);
  expect(state.selectionPosts).toHaveLength(0);
});

test("判断下書きは切替を止め、画面移動・再読込・保存結果不明でも元の根拠と同じidを保持する", async ({ page }) => {
  const state = await storedComparison(page);
  await page.goto("/?mode=reference");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  const btc = panel.locator('[data-target="asset:BTC"]');
  const eth = panel.locator('[data-target="asset:ETH"]');
  await btc.getByRole("button", { name: "監視を記録" }).click();
  await panel.getByLabel("判断理由").fill("元の100 USDTを根拠に監視");
  await expect(btc.getByRole("button", { name: "監視を記録" })).toBeDisabled();
  await expect(eth.getByRole("button", { name: "この成立を見送り" })).toBeDisabled();
  await expect(btc.getByRole("button", { name: "この実Venueを確認", includeHidden: true })).toBeDisabled();
  state.source.rows.find(row => row.asset === "BTC")!.raw.referenceClose.value = 105;
  await page.clock.fastForward(15_000);
  await page.getByRole("button", { name: "一覧に戻る", exact: true }).click();
  await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "設定", exact: true }).click();
  await expect(page).toHaveURL(/\/settings/);
  await page.getByRole("navigation", { name: "メインメニュー" }).getByRole("link", { name: "ランキング", exact: true }).click();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の100 USDTを根拠に監視");
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の100 USDTを根拠に監視");
  await expect(panel.getByRole("form", { name: "判断を保存" })).toContainText("asset:BTC · 監視 · 成立 episode-BTC-1");
  state.decisionResponseLost = true;
  await panel.getByRole("button", { name: "判断を保存", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("判断を保存できません");
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の100 USDTを根拠に監視");
  await expect(panel.getByLabel("判断理由")).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の100 USDTを根拠に監視");
  await panel.getByRole("button", { name: "判断を保存", exact: true }).click();
  await expect(panel.getByRole("form", { name: "判断を保存" })).toHaveCount(0);
  expect(state.decisions).toHaveLength(2);
  expect(state.decisions[1].decision).toEqual(state.decisions[0].decision);
  expect(state.history.decisions).toHaveLength(1);
  expect((state.history.decisions[0].snapshot.row as typeof state.source.rows[0]).raw.referenceClose.value).toBe(100);
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByRole("form", { name: "判断を保存" })).toHaveCount(0);
  expect(state.selectionPosts).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("復元下書きの対象や成立が変わった場合は保存を止め、明示破棄まで本文を保持する", async ({ page }) => {
  const state = await storedComparison(page);
  await page.goto("/?mode=reference");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  await panel.locator('[data-target="asset:BTC"]').getByRole("button", { name: "この成立を見送り" }).click();
  await panel.getByLabel("判断理由").fill("元の成立だけを見送る");
  state.source.rows.find(row => row.asset === "BTC")!.episodeId = "episode-BTC-2";
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の成立だけを見送る");
  await expect(panel.getByRole("form", { name: "判断を保存" })).toContainText("成立が変更");
  await expect(panel.getByRole("button", { name: "判断を保存", exact: true })).toBeDisabled();
  state.source.rows.find(row => row.asset === "BTC")!.originals[0].versionId = 2;
  state.source.rows.find(row => row.asset === "BTC")!.native[0].versionId = 2;
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("元の成立だけを見送る");
  await expect(panel.getByRole("form", { name: "判断を保存" })).toContainText("対象が変更");
  await expect(panel.getByRole("button", { name: "判断を保存", exact: true })).toBeDisabled();
  await panel.getByRole("button", { name: "下書きを破棄", exact: true }).click();
  await page.reload();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByRole("form", { name: "判断を保存" })).toHaveCount(0);
  expect(state.decisions).toHaveLength(0);
  expect(state.selectionPosts).toHaveLength(0);
});

test("タブ保存が使えない場合は警告し、画面内の判断下書きを編集・保存できる", async ({ page }) => {
  const state = await storedComparison(page);
  await page.addInitScript(() => {
    for (const method of ["getItem", "setItem", "removeItem"] as const) {
      const original = Storage.prototype[method];
      Storage.prototype[method] = function(key: string, value?: string) {
        if (this === window.sessionStorage && key.startsWith("watchdeck:discovery-decision-draft:")) {
          throw new DOMException("Fixture session storage unavailable", "SecurityError");
        }
        return Reflect.apply(original, this, [key, value]);
      };
    }
  });
  await page.goto("/?mode=reference");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  await panel.locator('[data-target="asset:BTC"]').getByRole("button", { name: "監視を記録" }).click();
  await panel.getByLabel("判断理由").fill("この画面内の下書き");
  await expect(panel).toContainText("この画面を閉じると失われる可能性");
  await expect(panel.getByLabel("判断理由")).toHaveValue("この画面内の下書き");
  await panel.getByRole("button", { name: "下書きを破棄", exact: true }).click();
  await expect(panel.getByRole("form", { name: "判断を保存" })).toHaveCount(0);
  await panel.locator('[data-target="asset:BTC"]').getByRole("button", { name: "監視を記録" }).click();
  await panel.getByLabel("判断理由").fill("この画面内の下書き");
  await panel.getByRole("button", { name: "判断を保存", exact: true }).click();
  await expect(panel.getByRole("form", { name: "判断を保存" })).toHaveCount(0);
  expect(state.history.decisions[0].reason).toBe("この画面内の下書き");
  expect(state.selectionPosts).toHaveLength(0);
});

test("候補4件を解除・再読込後も保持し、判断根拠を固定して明示確認でのみ実Venueへ移る", async ({ page }, testInfo) => {
  // Align the simulated observation timeline independently of the wall-clock minute.
  let now = Math.floor(Date.now() / 60_000) * 60_000 + 10_000;
  await page.clock.install({ time: new Date(now) });
  let source = discoveryFixture(now);
  let workspace: UserWorkspace = { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] };
  let history: DecisionHistory = { schemaVersion: 1, revision: 0, decisions: [] };
  let selected = "bitget:ETHUSDT";
  let generationConflicts = 0;
  let detailFailures = 0;
  const detailQueries: string[][] = [];
  const selectionPosts: unknown[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", cause => pageErrors.push(cause.message));
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams, source.rankingCutoff!) }));
  await page.route("**/api/discovery-summary", route => route.fulfill({ json: {
    schemaVersion: "discovery-summary-v1", policy: source.policy, generationId: source.generationId,
    decisionAt: source.decisionAt, rankingCutoff: source.rankingCutoff, status: source.status,
    reason: source.reason, historyAvailableFrom: source.historyAvailableFrom,
    rows: source.rows.map(({ raw: _raw, native: _native, turnoverComparison: _comparison, ...row }) => row)
  } }));
  await page.route("**/api/discovery?**", route => {
    const query = new URL(route.request().url()).searchParams;
    const ids = query.getAll("assetId");
    detailQueries.push(ids);
    if (generationConflicts > 0) {
      generationConflicts--;
      return route.fulfill({ status: 409, json: { error: "discovery_generation_changed" } });
    }
    if (detailFailures > 0) {
      detailFailures--;
      return route.fulfill({ status: 503, json: { error: "discovery_unavailable" } });
    }
    expect(ids.length).toBeGreaterThan(0); expect(ids.length).toBeLessThanOrEqual(4);
    expect(query.get("generationId")).toBe(source.generationId);
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
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel).toContainText("固定監視: 15分");
  for (const asset of ["BTC", "ETH", "SOL", "MISSING"]) {
    await panel.getByRole("button", { name: new RegExp(`^${asset} ·`) }).click();
    await expect(panel.locator(`[data-target="asset:${asset}"]`)).toBeVisible();
    await expect(page.getByRole("dialog").getByRole("status")).toContainText(`${asset}を比較に追加しました`);
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
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByTestId("comparison-card")).toHaveCount(4);
  const btc = panel.locator('[data-target="asset:BTC"]');
  await btc.getByRole("button", { name: "この成立を見送り" }).click();
  await panel.getByLabel("判断理由").fill("板が薄いので見送り");
  await page.getByRole("button", { name: "一覧に戻る", exact: true }).click();
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(panel.getByLabel("判断理由")).toHaveValue("板が薄いので見送り");
  const oldClose = source.rows.find(row => row.asset === "BTC")!.raw.referenceClose.value;
  source.rows.find(row => row.asset === "BTC")!.raw.referenceClose.value = 105;
  const savedPins = structuredClone(workspace.pins);
  generationConflicts = 2;
  now += 15000; await page.clock.fastForward(15000);
  await expect(page.getByRole("dialog").getByRole("status")).toContainText("更新待ち");
  await expect(panel.getByRole("button", { name: "判断を保存", exact: true })).toBeDisabled();
  await expect(btc.getByRole("button", { name: "この実Venueを確認", includeHidden: true })).toBeDisabled();
  expect(workspace.pins).toEqual(savedPins); expect(history.decisions).toHaveLength(0);
  detailFailures = 1;
  now += 15000; await page.clock.fastForward(15000);
  await expect(page.getByRole("dialog").getByRole("status")).toContainText("更新待ち");
  await expect(panel.getByRole("button", { name: "判断を保存", exact: true })).toBeDisabled();
  now += 15000; await page.clock.fastForward(15000);
  await expect(panel.getByRole("button", { name: "判断を保存", exact: true })).toBeEnabled();
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
  // The extra conflict/outage cycles age the frozen fixture beyond its freshness gate.
  // Publish a genuinely newer provider generation before confirming a native selection.
  now += 15000; source = discoveryFixture(now); await page.clock.fastForward(15000);
  await btc.locator("summary").filter({ hasText: "実Venue:" }).click();
  await btc.getByRole("button", { name: "この実Venueを確認", includeHidden: true }).click();
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
  expect(detailQueries.every(ids => ids.length > 0 && ids.length <= 4)).toBe(true);
});

test("条件履歴を再展開すると最新状態を取り込み、既読ページと続き位置を保持する", async ({ page }) => {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  const source = discoveryFixture(now);
  const [first, older, newest, oldest] = source.episodes;
  let refreshed = false;
  const historyQueries: string[] = [];
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams, source.rankingCutoff!) }));
  await page.route("**/api/discovery-summary", route => route.fulfill({ json: discoverySummaryFixture(now) }));
  await page.route("**/api/user-workspace", route => route.fulfill({ json: { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] } }));
  await page.route("**/api/decisions", route => route.fulfill({ json: { schemaVersion: 1, revision: 0, decisions: [] } }));
  await page.route("**/api/discovery?**", route => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.getAll("assetId")).toEqual([]);
    const cursor = query.get("cursor") ?? "";
    historyQueries.push(cursor);
    const episodes = cursor === "older-page" ? [older] : cursor === "oldest-page" ? [oldest]
      : refreshed ? [{ ...first, state: "ended", endedAt: now, endReason: "condition_not_matched" }, newest] : [first];
    return route.fulfill({ json: { ...source, episodes,
      nextCursor: cursor === "oldest-page" ? null : cursor === "older-page" ? "oldest-page" : "older-page" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  const panel = page.getByTestId("discovery-workflow");
  const toggle = panel.locator("summary").filter({ hasText: /^条件履歴/ });
  const historyPanel = toggle.locator("..");
  await toggle.click();
  await expect(historyPanel).toContainText(`${first.asset} · 新規成立 · active`);
  await historyPanel.getByRole("button", { name: "条件履歴をさらに読む" }).click();
  await expect(historyPanel).toContainText(`${older.asset} · 新規成立 · active`);
  await toggle.click();
  refreshed = true;
  await page.clock.fastForward(15_000);
  expect(historyQueries).toEqual(["", "older-page"]);
  await toggle.click();
  await expect(historyPanel).toContainText(`${first.asset} · 新規成立 · ended`);
  await expect(historyPanel).toContainText(`${newest.asset} · 新規成立 · active`);
  await expect(historyPanel).toContainText(`${older.asset} · 新規成立 · active`);
  await historyPanel.getByRole("button", { name: "条件履歴をさらに読む" }).click();
  await expect(historyPanel).toContainText(`${oldest.asset} · 新規成立 · active`);
  expect(historyQueries).toEqual(["", "older-page", "", "oldest-page"]);
});

test("旧Attentionの候補APIが未対応でもMarketsのランキングを利用できる", async ({ page }) => {
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/discovery-summary", route => route.fulfill({ status: 503, json: { error: "discovery_unavailable" } }));
  await page.route("**/api/user-workspace", route => route.fulfill({ json: { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] } }));
  await page.route("**/api/decisions", route => route.fulfill({ json: { schemaVersion: 1, revision: 0, decisions: [] } }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams) }));
  await page.goto("/");
  await page.getByRole("button", { name: /候補・比較/ }).click();
  await expect(page.getByTestId("discovery-workflow")).toContainText("候補機能を利用できません");
  await expect(page.getByTestId("ranking-row").first()).toBeVisible();
});

async function panelFixture(page: Page, count = 100, saved = 4) {
  const now = Date.now();
  await page.clock.install({ time: new Date(now) });
  const fixture = discoveryFixture(now);
  const template = fixture.rows[0];
  let source = { ...fixture, rows: Array.from({ length: count }, (_, index) => {
    if (index === 0) return structuredClone(template);
    const row = structuredClone(template);
    row.asset = `COIN${String(index).padStart(3, "0")}`;
    row.assetId = `asset:${row.asset}`; row.identityKey = `identity-${row.asset}`;
    row.referenceKey = `bybit:${row.asset}USDT:fixture-v1`; row.episodeId = `episode-${row.asset}`;
    row.raw.asset = row.asset; row.raw.assetId = row.assetId; row.raw.referenceKey = row.referenceKey;
    return row;
  }), episodes: [] };
  let workspace: UserWorkspace = { schemaVersion: 2, revision: 0, favorites: [], savedViews: [],
    pins: source.rows.slice(0, saved).map(row => ({
      target: { kind: "reference" as const, id: row.assetId, referenceKey: row.referenceKey!,
        originals: row.originals.map(item => `${item.instrumentId}:${item.versionId}`).sort() },
      discoveredAt: row.raw.decisionAt, episodeId: row.episodeId,
      snapshot: { asset: row.asset, referenceClose: row.raw.referenceClose }
    })) };
  let failure = 0;
  let offline = false;
  let requests = 0;
  let writes = 0;
  const selections: unknown[] = [];
  await page.route("https://s3.tradingview.com/**", route => route.fulfill({ body: "" }));
  await page.route("**/api/rankings?**", route => route.fulfill({ json: rankingFixture(new URL(route.request().url()).searchParams, fixture.rankingCutoff!) }));
  await page.route("**/api/discovery-summary", route => route.fulfill(offline
    ? { status: 503, json: { error: "unavailable" } } : { json: {
      schemaVersion: "discovery-summary-v1", policy: source.policy, generationId: source.generationId,
      decisionAt: source.decisionAt, rankingCutoff: source.rankingCutoff, status: source.status,
      reason: source.reason, historyAvailableFrom: source.historyAvailableFrom,
      rows: source.rows.map(({ raw: _raw, native: _native, turnoverComparison: _comparison, ...row }) => row)
    } }));
  await page.route("**/api/discovery?**", route => {
    requests++;
    if (offline) return route.fulfill({ status: 503, json: { error: "unavailable" } });
    const ids = new URL(route.request().url()).searchParams.getAll("assetId");
    return route.fulfill({ json: { ...source, rows: ids.length ? source.rows.filter(row => ids.includes(row.assetId)) : source.rows } });
  });
  await page.route("**/api/user-workspace", route => {
    if (route.request().method() === "POST") {
      writes++;
      if (failure) return route.fulfill({ status: failure, json: { error: "fixture" } });
      const command = route.request().postDataJSON();
      if (command.enabled && workspace.pins.length === 4) return route.fulfill({ status: 413, json: { error: "workspace_limit" } });
      workspace = { ...workspace, revision: workspace.revision + 1, pins: command.enabled ? [...workspace.pins, command.pin]
        : workspace.pins.filter(pin => pin.target.id !== command.pin.target.id) };
    }
    return route.fulfill({ json: workspace });
  });
  await page.route("**/api/decisions", route => route.fulfill({ json: { schemaVersion: 1, revision: 0, decisions: [] } }));
  await page.route("**/api/market-data", route => route.fulfill({ json: marketBundle(now) }));
  await page.route("**/api/selection", route => { selections.push(route.request().postDataJSON()); return route.fulfill({ json: { ok: true } }); });
  return { get source() { return source; }, set source(value) { source = value; },
    get requests() { return requests; }, get writes() { return writes; },
    fail: (status: number) => { failure = status; }, offline: () => { offline = true; }, selections };
}

test("大量候補でも初期一覧を妨げず、パネルの開閉で位置・focusと候補検索を保持する", async ({ page }, testInfo) => {
  const state = await panelFixture(page);
  await page.goto("/?mode=native");
  const entry = page.getByRole("button", { name: /候補・比較/ });
  await expect(entry).toContainText("保存4/4");
  const dialog = page.getByRole("dialog", { name: "候補・比較" });
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("heading", { name: "取引所別", exact: true })).toBeInViewport();
  expect(await page.getByTestId("discovery-workflow").evaluate(node => node.getBoundingClientRect().height)).toBeLessThan(120);
  await entry.focus();
  const originalScroll = await page.evaluate(() => ({ x: scrollX, y: scrollY }));
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "一覧に戻る" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await dialog.evaluate(node => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "一覧に戻る" })).toBeFocused();
  if (page.viewportSize()!.width > 768) {
    await page.mouse.click(10, 100);
    await expect(dialog).toBeVisible();
  }
  await expect(dialog.getByTestId("comparison-card")).toHaveCount(4);
  expect(await dialog.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  const box = (await dialog.boundingBox())!;
  const viewport = page.viewportSize()!;
  if (viewport.width <= 768) { expect(box.width).toBe(viewport.width); expect(box.height).toBe(viewport.height); }
  else { expect(box.width).toBeLessThanOrEqual(720); expect(box.x + box.width).toBe(viewport.width); }
  await page.screenshot({ path: testInfo.outputPath("comparison-panel.png") });
  const list = dialog.getByRole("region", { name: "成立候補" });
  await expect(list.getByRole("button", { name: /比較へ/ })).toHaveCount(10);
  await list.getByRole("button", { name: "次の10件" }).click();
  await expect(list).toContainText("2 / 10");
  const before = state.requests;
  await page.clock.fastForward(15000);
  await expect.poll(() => state.requests).toBeGreaterThan(before);
  await expect(list).toContainText("2 / 10");
  await list.getByLabel("候補の銘柄検索").fill("COIN09");
  await expect(list).toContainText("1 / 1");
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(entry).toBeFocused();
  expect(await page.evaluate(() => ({ x: scrollX, y: scrollY }))).toEqual(originalScroll);
  await entry.click();
  await expect(list.getByLabel("候補の銘柄検索")).toHaveValue("COIN09");
  await list.getByLabel("候補の銘柄検索").fill("");
  await list.getByRole("button", { name: "次の10件" }).click();
  state.source = { ...state.source, rows: state.source.rows.slice(0, 5) };
  await page.clock.fastForward(15000);
  await expect(list).toContainText("1 / 1");
  await page.keyboard.press("Escape");
  state.source.status = "stale";
  await page.clock.fastForward(15000);
  await expect(page.getByTestId("discovery-workflow").getByRole("status")).toContainText("前回の観測");
  state.source.status = "partial";
  await page.clock.fastForward(15000);
  await expect(page.getByTestId("discovery-workflow").getByRole("status")).toContainText("一部確認不能");
  state.offline();
  await page.clock.fastForward(15000);
  await expect(page.getByTestId("discovery-workflow").getByRole("status")).toContainText("候補機能を利用できません");
  await entry.click();
  await expect(dialog.getByTestId("comparison-card")).toHaveCount(4);
  expect(state.selections).toEqual([]);
  await page.keyboard.press("Escape");
  // A shorter viewport creates real page scroll without changing page content.
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 400 });
  await page.evaluate(() => { window.scrollTo(0, 150); });
  const scrolled = await page.evaluate(() => scrollY);
  expect(scrolled).toBeGreaterThan(0);
  await entry.evaluate(node => (node as HTMLButtonElement).focus({ preventScroll: true }));
  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(entry).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBe(scrolled);
});

test("一覧の比較追加は非遷移で通知し、重複と保存失敗も一覧から確認できる", async ({ page }) => {
  const state = await panelFixture(page, 5, 0);
  await page.goto("/?mode=reference");
  const add = page.getByRole("button", { name: "BTCを比較へ追加", exact: true });
  await expect(page.getByRole("button", { name: /候補・比較/ })).toContainText("保存0/4");
  await add.click();
  const notice = page.getByTestId("comparison-feedback");
  await expect(notice).toContainText("BTCを比較に追加しました");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  const scroll = await page.evaluate(() => scrollY);
  await add.click();
  await expect(notice).toContainText("BTCは追加済みです");
  expect(state.writes).toBe(1);
  const view = notice.getByRole("button", { name: "比較を見る" });
  await view.click();
  await expect(page.getByTestId("comparison-card")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(view).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBe(scroll);
  for (const [status, message] of [[413, "最大4件"], [409, "更新されました"], [500, "保存できません"]] as const) {
    state.fail(status);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("watchdeck:compare", { detail: { assetId: "asset:COIN001" } })));
    await expect(notice.getByRole("alert")).toContainText(message);
    await expect(page.getByRole("dialog")).not.toBeVisible();
  }
  expect(state.selections).toEqual([]);
});
