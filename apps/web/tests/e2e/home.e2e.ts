import { expect, test, type Locator, type Page, type Route } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const scannerCoreDir = resolve(process.cwd(), "../scanner-core");
const e2ePaths = resolveWebTestStatePaths("e2e");
const snapshotPath = e2ePaths.snapshotPath;
const pastNotesDir = e2ePaths.pastNotesDir;
const pastNotesPath = resolve(pastNotesDir, "current.json");
const dashboardViewSettingsDir = e2ePaths.dashboardViewSettingsDir;

test.describe.configure({ mode: "serial" });

function generateSnapshot(fixtureSet: string) {
  execFileSync(
    "uv",
    [
      "run",
      "watchdeck",
      "scan",
      "--source",
      "fixture",
      "--fixture-set",
      fixtureSet,
      "--template",
      "balanced"
    ],
    {
      cwd: scannerCoreDir,
      env: {
        ...process.env,
        PREP_WATCHDECK_STATE_DIR: e2ePaths.runtimeRoot
      },
      stdio: "pipe"
    }
  );
}

function addVpiLitePlusSnapshotPayload() {
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8")) as {
    generatedAt: number;
    summary: Record<string, unknown>;
    rows: Array<{ symbol: string; display?: Record<string, unknown> }>;
  };
  const item = {
    symbol: "THINUSDT",
    state: "EARLY_ACTIVITY",
    score: 48.5,
    reasonCodes: ["ABS_RETURN_UP", "TURNOVER_UP"],
    riskTagCodes: ["THIN_TURNOVER"],
    fundingState: "NORMAL",
    openInterestState: "AVAILABLE",
    dataQuality: "OK",
    dataAsOf: snapshot.generatedAt - 60_000
  };
  snapshot.summary.vpiLitePlus = {
    schemaVersion: 1,
    mode: "lite_plus_v0",
    generatedAt: snapshot.generatedAt,
    benchmarks: [
      { ...item, symbol: "BTCUSDT", state: "CALM", score: 12.5 },
      { ...item, symbol: "ETHUSDT", state: "DATA_STALE", score: 0, dataQuality: "STALE" }
    ],
    targets: [item]
  };
  const row = snapshot.rows.find((candidate) => candidate.symbol === item.symbol);
  if (!row) throw new Error("THINUSDT fixture row not found");
  row.display = { ...row.display, vpiLitePlus: item };
  writeFileSync(snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf-8");
}

function marketRow(watchlist: Locator, symbol: string) {
  return watchlist.locator(`[data-market-row][data-symbol="${symbol}"]`);
}

function marketRowButton(watchlist: Locator, symbol: string) {
  return marketRow(watchlist, symbol).locator("[data-row-select]");
}

async function expectTextColorToken(locator: Locator, tokenName: "--up" | "--down") {
  await expect(locator).toBeVisible();
  const colors = await locator.evaluate((element, token) => {
    const probe = document.createElement("span");
    probe.style.color = getComputedStyle(document.documentElement).getPropertyValue(token);
    document.body.append(probe);
    const expected = getComputedStyle(probe).color;
    probe.remove();
    return { actual: getComputedStyle(element).color, expected };
  }, tokenName);
  expect(colors.actual).toBe(colors.expected);
}

async function openDetailGroup(detail: Locator, group: "context") {
  const node = detail.locator(`details[data-detail-group="${group}"]`);
  if ((await node.getAttribute("open")) === null) {
    await node.locator("summary").first().click();
  }
}

async function expectDeferredMutationState({
  page,
  endpoint,
  method,
  button,
  busyLabel,
  successStatus,
  whilePending,
  beforeSuccess,
  afterSuccess,
  responseStatus
}: {
  page: Page;
  endpoint: string;
  method: "POST" | "PATCH" | "DELETE";
  button: Locator;
  busyLabel: string;
  successStatus: Locator;
  whilePending?: () => Promise<void>;
  beforeSuccess?: () => Promise<void>;
  afterSuccess?: () => Promise<void>;
  responseStatus?: number;
}) {
  let releaseRequest = () => {};
  const requestGate = new Promise<void>((resolve) => {
    releaseRequest = resolve;
  });
  let markRouteSettled = () => {};
  const routeSettled = new Promise<void>((resolve) => {
    markRouteSettled = resolve;
  });
  let matchingCalls = 0;
  const routeHandler = async (route: Route) => {
    if (route.request().method() !== method) {
      await route.continue();
      return;
    }
    matchingCalls += 1;
    try {
      await requestGate;
      if (responseStatus) {
        await route.fulfill({
          status: responseStatus,
          contentType: "application/json",
          body: JSON.stringify({ error: "forced mutation failure" })
        });
      } else {
        await route.continue();
      }
    } finally {
      markRouteSettled();
    }
  };

  await page.route(endpoint, routeHandler);
  try {
    await button.click();
    await expect.poll(() => matchingCalls).toBe(1);
    await expect(button).toBeDisabled();
    await expect(button).toHaveAttribute("aria-busy", "true");
    await expect(button).toHaveText(busyLabel);

    await button.evaluate((element) =>
      element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
    );
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(matchingCalls).toBe(1);

    await whilePending?.();
    releaseRequest();
    await beforeSuccess?.();
    await expect(successStatus).toBeVisible();
    await afterSuccess?.();
  } finally {
    releaseRequest();
    if (matchingCalls > 0) await routeSettled;
    await page.unroute(endpoint, routeHandler);
  }
}

test.afterAll(() => {
  generateSnapshot("basic");
  rmSync(pastNotesDir, { recursive: true, force: true });
  rmSync(dashboardViewSettingsDir, { recursive: true, force: true });
});

test("fixture backed dashboard renders the current Japanese UI", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "ローカル市場監視" })).toBeVisible();
  await expect(page.locator(".source-banner")).toContainText("検証データ");
  await expect(page.locator(".source-banner")).toContainText("正常");
  await expect(page.locator(".source-banner")).toContainText("基本");
  await expect(page.getByText("Service 状態なし")).toBeVisible();

  const categories = page.getByRole("complementary", { name: "分類" });
  await expect(categories.getByRole("button", { name: /すべて\s+5/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /注視\s+2/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /注意\s+1/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /監視除外候補\s+1/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /低優先\s+1/ })).toBeVisible();
  await expect(
    page.getByText("74h条件: 価格±4%以上 かつ 24h売買代金+15%以上（合致1 / 未一致0 / 判定不能3）", { exact: true })
  ).toBeVisible();

  const rankings = page.getByRole("region", { name: "15m ランキング" });
  const changeUpPanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "上昇順", exact: true }) });
  const volumePanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "売買代金" }) });
  const volumeRatioPanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "15分出来高倍率" }) });
  await expect(changeUpPanel.getByRole("link", { name: /ALT\s+2\.1%/ })).toBeVisible();
  await expect(changeUpPanel.getByText("表示 1/1")).toBeVisible();
  await expect(volumePanel.getByRole("link", { name: /ALT\s+89,000/ })).toBeVisible();
  await expect(volumePanel.getByText("表示 1/1")).toBeVisible();
  await expect(volumeRatioPanel.getByRole("link", { name: /ALT\s+3\.4/ })).toBeVisible();
  await expect(volumeRatioPanel.getByRole("link", { name: /ALT\s+3\.4/ })).toHaveAttribute(
    "href",
    /\/symbols\/ALTUSDT\?tf=15m$/
  );
  await expect(volumeRatioPanel.getByText("表示 1/1")).toBeVisible();

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(watchlist.getByRole("heading", { name: "精密監視リスト" })).toBeVisible();
  await expect(watchlist.getByText("表示 5 / 全 5")).toBeVisible();
  const altRow = marketRow(watchlist, "ALTUSDT");
  await expect(altRow).toBeVisible();
  await expect(altRow).toContainText("出来高確認済み上昇");
  await expect(altRow.locator('[data-price-source="snapshot"]')).toHaveText("1.23");
  await expect(marketRow(watchlist, "THINUSDT")).toContainText("薄商い急変");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByRole("region", { name: "VPI-Lite+ 実験表示" })).toHaveCount(0);
  await expect(watchlist.getByText("Raw Sort: 15m 価格変化 大きい順")).toBeVisible();
  await expect(watchlist.locator(".market-header").getByText("現在価格")).toBeVisible();
  await expect(watchlist.locator(".market-header").getByText("15分出来高倍率")).toBeVisible();
  await expect(watchlist.getByText("詳細な並び替え")).toBeVisible();
  await expect(watchlist.getByLabel("Raw Sortキー")).not.toBeVisible();
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();
  const sections = await page
    .locator("[data-dashboard-section]")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-dashboard-section")));
  expect(sections).toEqual(["candidate", "watchlist", "detail", "smart-rank"]);

  const monitoringMaterialBox = await detail.getByRole("region", { name: "監視材料" }).boundingBox();
  const statsBox = await detail.getByText("15分変化率").boundingBox();
  const contextSummaryBox = await detail
    .locator('details[data-detail-group="context"] summary')
    .boundingBox();
  expect(monitoringMaterialBox?.y).toBeLessThan(statsBox?.y ?? 0);
  expect(statsBox?.y).toBeLessThan(contextSummaryBox?.y ?? 0);
  await expect(detail.getByText("15分変化率")).toBeVisible();
  await expect(detail.getByText("データ網羅率")).toBeVisible();
  await openDetailGroup(detail, "context");
  await expect(detail.getByText("銘柄への注意・クセ・過去反応")).toBeVisible();
  await expect(detail.getByRole("heading", { name: "理由", exact: true })).toBeVisible();
});

test("shows VPI experiment states without turning the dashboard into a score ranking", async ({
  page
}) => {
  generateSnapshot("basic");
  addVpiLitePlusSnapshotPayload();
  await page.goto("/");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  const panel = detail.getByRole("region", { name: "VPI-Lite+ 実験表示" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("実験中の補助指標です。売買シグナルではありません。")).toBeVisible();
  await expect(panel.getByText("Benchmark")).toHaveCount(2);
  await expect(panel.getByText("Target")).toHaveCount(1);
  await expect(panel.getByText("平常")).toBeVisible();
  await expect(panel.getByText("データ遅延")).toBeVisible();
  await expect(panel.getByText("活動増加")).toBeVisible();
  await expect(panel).not.toContainText("48.5");

  const selectedVpi = detail.getByRole("region", { name: "選択銘柄 VPI補助詳細" });
  await expect(selectedVpi).toBeVisible();
  await expect(selectedVpi.getByText("VPI補助値 48.5 / 100")).toBeVisible();
  await expect(selectedVpi.getByText("値動きの活動増加")).toBeVisible();
  await expect(selectedVpi.getByText("売買代金が薄い")).toBeVisible();
  await expect(selectedVpi.getByText("取得あり")).toBeVisible();

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(watchlist.locator(".market-header")).not.toContainText("VPI");
});

test("ignores a malformed VPI summary without breaking the dashboard", async ({ page }) => {
  generateSnapshot("basic");
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8"));
  snapshot.summary.vpiLitePlus = {
    schemaVersion: 1,
    mode: "lite_plus_v0",
    generatedAt: snapshot.generatedAt,
    benchmarks: [{ symbol: "BTCUSDT", state: "BUY_NOW", score: Number.NaN }],
    targets: "invalid"
  };
  writeFileSync(snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf-8");

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "ローカル市場監視" })).toBeVisible();
  await expect(page.getByRole("region", { name: "VPI-Lite+ 実験表示" })).toHaveCount(0);
});

test("falls back to the generic 74h candidate rule when summary metadata is malformed", async ({
  page
}) => {
  generateSnapshot("basic");
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8"));
  snapshot.summary.candidateRule74h = { operator: "AND", priceAbsPct: "4" };
  writeFileSync(snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf-8");

  await page.goto("/");

  await expect(
    page.getByText("74h候補条件の詳細を取得できません。snapshot更新後に再確認してください。", {
      exact: true
    })
  ).toBeVisible();
});

test("labels mixed-sign change rankings by sort order and colors each value by actual sign", async ({
  page
}) => {
  generateSnapshot("basic");
  const snapshot = JSON.parse(readFileSync(snapshotPath, "utf-8"));
  snapshot.rankings.timeframes["15m"].changeUp = [
    { symbol: "ALTUSDT", value: 2.1 },
    { symbol: "DUMPUSDT", value: -2.4 }
  ];
  snapshot.rankings.timeframes["15m"].changeDown = [
    { symbol: "DUMPUSDT", value: -2.4 },
    { symbol: "ALTUSDT", value: 2.1 }
  ];
  snapshot.rankings.meta.timeframes["15m"].changeUp.totalEligible = 2;
  snapshot.rankings.meta.timeframes["15m"].changeDown.totalEligible = 2;
  writeFileSync(snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf-8");
  await page.goto("/");

  const rankings = page.getByRole("region", { name: "15m ランキング" });
  const changeUpPanel = rankings.locator(".rank-panel").filter({
    has: page.getByRole("heading", { name: "上昇順", exact: true })
  });
  const changeDownPanel = rankings.locator(".rank-panel").filter({
    has: page.getByRole("heading", { name: "下落順", exact: true })
  });

  await expect(changeUpPanel.getByRole("heading", { name: "上昇順", exact: true })).toBeVisible();
  await expect(changeDownPanel.getByRole("heading", { name: "下落順", exact: true })).toBeVisible();
  await expect(changeUpPanel.locator(".rank-row").first()).toContainText(/ALT\s+2\.1%/);
  await expect(changeUpPanel.locator(".rank-row").last()).toContainText(/DUMP\s+-2\.4%/);
  await expect(changeDownPanel.locator(".rank-row").first()).toContainText(/DUMP\s+-2\.4%/);
  await expect(changeDownPanel.locator(".rank-row").last()).toContainText(/ALT\s+2\.1%/);

  await expectTextColorToken(
    changeUpPanel.getByRole("link", { name: /ALT\s+2\.1%/ }).locator("strong"),
    "--up"
  );
  await expectTextColorToken(
    changeUpPanel.getByRole("link", { name: /DUMP\s+-2\.4%/ }).locator("strong"),
    "--down"
  );
  await expectTextColorToken(
    changeDownPanel.getByRole("link", { name: /DUMP\s+-2\.4%/ }).locator("strong"),
    "--down"
  );
  await expectTextColorToken(
    changeDownPanel.getByRole("link", { name: /ALT\s+2\.1%/ }).locator("strong"),
    "--up"
  );
});

test("can switch ranking timeframe and display view filters", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  await page.getByRole("group", { name: "時間軸" }).getByRole("button", { name: "4h", exact: true }).click();
  const rankings = page.getByRole("region", { name: "4h ランキング" });
  const changeUpPanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "上昇順", exact: true }) });
  const volumePanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "売買代金" }) });
  const volumeRatioPanel = rankings
    .locator(".rank-panel")
    .filter({ has: page.getByRole("heading", { name: "15分出来高倍率" }) });

  await expect(changeUpPanel.getByRole("link", { name: /ALT\s+2\.2%/ })).toBeVisible();
  await expect(volumePanel.getByRole("link", { name: /ALT\s+820,000/ })).toBeVisible();
  await expect(volumeRatioPanel.getByRole("link", { name: /ALT\s+3\.4/ })).toHaveAttribute(
    "href",
    /\/symbols\/ALTUSDT\?tf=15m$/
  );

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(watchlist.getByText("表示 5 / 全 5")).toBeVisible();

  await page.getByRole("group", { name: "ビュー" }).getByRole("button", { name: "急落" }).click();
  await expect(watchlist.getByText("表示 1 / 全 5")).toBeVisible();
  await expect(marketRow(watchlist, "DUMPUSDT")).toContainText("価格先行・出来高弱め");
  await expect(marketRow(watchlist, "ALTUSDT")).toHaveCount(0);
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByText("選択銘柄を保持中")).toBeVisible();
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();
  await expect(detail.getByText("対象が再表示されるまで保存できません")).toBeVisible();

  await page.getByRole("group", { name: "ビュー" }).getByRole("button", { name: "注視のみ" }).click();
  await expect(watchlist.getByText("表示 2 / 全 5")).toBeVisible();
  await expect(marketRow(watchlist, "ALTUSDT")).toContainText("出来高確認済み上昇");
  await expect(marketRow(watchlist, "NEWALTUSDT")).toContainText("出来高先行");
});

test("can save and reset dashboard view settings", async ({ page }) => {
  generateSnapshot("basic");
  rmSync(dashboardViewSettingsDir, { recursive: true, force: true });
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await page.getByRole("group", { name: "ビュー" }).getByRole("button", { name: "急騰" }).click();
  await expect(watchlist.getByText("表示 1 / 全 5")).toBeVisible();

  await watchlist.getByText("表示条件設定").click();
  const surgeSettings = watchlist.getByRole("region", { name: "急騰表示条件" });
  await surgeSettings.getByLabel("急騰 15m 閾値").fill("3");
  await surgeSettings.getByRole("button", { name: "保存" }).click();
  await expect(watchlist.getByText("表示 0 / 全 5")).toBeVisible();
  await expect(marketRow(watchlist, "ALTUSDT")).toHaveCount(0);

  await surgeSettings.getByRole("button", { name: "既定値" }).click();
  await expect(watchlist.getByText("表示 1 / 全 5")).toBeVisible();
  await expect(marketRow(watchlist, "ALTUSDT")).toContainText("出来高確認済み上昇");
});

test("can raw sort the dashboard watchlist by initial movement, attention, and turnover", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const firstRow = watchlist.locator(".market-row").first();

  await expect(firstRow).toContainText("THIN");
  await expect(watchlist.getByText("Raw Sort: 15m 価格変化 大きい順")).toBeVisible();

  const fiveMinuteHeader = watchlist.getByRole("button", {
    name: "5m価格変化で並び替え",
    exact: true
  });
  await fiveMinuteHeader.click();
  await expect(firstRow).toContainText("ALT");
  await expect(watchlist.getByText("Raw Sort: 5m 価格変化 大きい順")).toBeVisible();

  await fiveMinuteHeader.click();
  await expect(firstRow).toContainText("DUMP");
  await expect(watchlist.getByText("Raw Sort: 5m 価格変化 小さい順")).toBeVisible();

  await fiveMinuteHeader.click();
  await expect(firstRow).toContainText("ALT");
  await expect(watchlist.getByText("Raw Sort: 5m 価格変化 大きい順")).toBeVisible();

  await watchlist
    .getByRole("group", { name: "時間軸ショートカット" })
    .getByRole("button", { name: "1h", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 1h 価格変化 大きい順")).toBeVisible();
  await expect(page.getByRole("region", { name: "1h ランキング" })).toBeVisible();
  await marketRowButton(watchlist, "ALTUSDT").click();
  await expect(
    page
      .getByRole("complementary", { name: "選択銘柄の詳細" })
      .getByRole("link", { name: "ALTUSDT の個別分析を開く" })
  ).toHaveAttribute("href", "/symbols/ALTUSDT?tf=1h");

  await watchlist
    .getByRole("group", { name: "観点ショートカット" })
    .getByRole("button", { name: "下落", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 1h 価格変化 小さい順")).toBeVisible();

  await watchlist
    .getByRole("group", { name: "観点ショートカット" })
    .getByRole("button", { name: "15分出来高倍率", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 15m 15分出来高倍率 大きい順")).toBeVisible();
  await expect(page.getByRole("region", { name: "15m ランキング" })).toBeVisible();

  await page
    .getByRole("region", { name: "15m ランキング" })
    .getByRole("button", { name: "15m", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 15m 15分出来高倍率 大きい順")).toBeVisible();

  await watchlist
    .getByRole("group", { name: "時間軸ショートカット" })
    .getByRole("button", { name: "1h", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 1h 価格変化 大きい順")).toBeVisible();

  await watchlist.getByText("詳細な並び替え").click();

  await watchlist.getByLabel("Raw Sortキー").selectOption("attentionScore");
  await expect(firstRow).toContainText("ALT");
  await expect(watchlist.getByText("Raw Sort: 1h 注目度 大きい順")).toBeVisible();

  await watchlist.getByLabel("Raw Sortキー").selectOption("changePct");

  await watchlist.getByLabel("Raw Sort順序").selectOption("asc");
  await expect(firstRow).toContainText("DUMP");
  await expect(watchlist.getByText("Raw Sort: 1h 価格変化 小さい順")).toBeVisible();

  await watchlist.getByLabel("Raw Sortキー").selectOption("turnoverUsdt");
  await expect(firstRow).toContainText("THIN");
  await expect(watchlist.getByText("Raw Sort: 1h 売買代金 小さい順")).toBeVisible();

  await watchlist.getByLabel("Raw Sort順序").selectOption("desc");
  await expect(firstRow).toContainText("DUMP");
  await expect(watchlist.getByText("Raw Sort: 1h 売買代金 大きい順")).toBeVisible();
});

test("keeps primary timeframe controls and the watchlist reachable at 390px", async ({ page }) => {
  generateSnapshot("basic");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(
    watchlist
      .getByRole("group", { name: "時間軸ショートカット" })
      .getByRole("button", { name: "1h", exact: true })
  ).toBeVisible();
  await expect(
    watchlist
      .getByRole("group", { name: "観点ショートカット" })
      .getByRole("button", { name: "15分出来高倍率", exact: true })
  ).toBeVisible();
  await expect(watchlist.getByText("詳細な並び替え")).toBeVisible();

  const firstRow = watchlist.locator(".market-row").first();
  await firstRow.scrollIntoViewIfNeeded();
  await expect(firstRow).toBeVisible();
});

test("selects a dashboard row before opening its chart-first symbol analysis", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const altRow = watchlist.locator('[data-market-row][data-symbol="ALTUSDT"]');
  const altSelect = altRow.getByRole("button", { name: "ALTUSDT を選択" });
  await altSelect.click();

  await expect(page).toHaveURL(/\/$/);
  await expect(altRow).toHaveClass(/selected/);
  await expect(altSelect).toHaveAttribute("aria-pressed", "true");
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByRole("heading", { name: "ALT" })).toBeVisible();
  const analysisLink = detail.getByRole("link", { name: "ALTUSDT の個別分析を開く" });
  await expect(analysisLink).toHaveAttribute("href", "/symbols/ALTUSDT?tf=15m");
  await analysisLink.click();

  await expect(page).toHaveURL(/\/symbols\/ALTUSDT\?tf=15m$/);
  await expect(page.getByRole("heading", { name: "ALT" })).toBeVisible();
  await expect(page.getByRole("region", { name: "ALT 分析" })).toBeVisible();
  await expect(page.getByRole("region", { name: "ALT チャート" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "時間軸別の変化と売買代金" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "監視材料" })).toBeVisible();
  await expect(page.getByText("ランキング位置")).toBeVisible();
  await expect(page.getByText("選択時間軸の掲載範囲")).toBeVisible();
  await expect(page.getByText("1件中 1位")).toHaveCount(4);
  await expect(page.getByRole("region", { name: "ALT 分析" }).getByText("出来高確認済み上昇")).toBeVisible();
  await expect(page.getByRole("region", { name: "補助情報" }).getByText("8.4%")).toBeVisible();

  await page.getByRole("region", { name: "主チャート" }).getByRole("link", { name: "4h", exact: true }).click();
  await expect(page).toHaveURL(/\/symbols\/ALTUSDT\?tf=4h$/);
  await expect(page.getByRole("region", { name: "ALT チャート" })).toContainText("ALT 4h 足");

  await page.getByRole("link", { name: "一覧へ" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("region", { name: "精密監視リスト" })).toBeVisible();
});

test("uses one roving tab stop and separates row focus from selection", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const rowButtons = watchlist.locator("[data-row-select]");
  const selectedButton = watchlist.locator('[data-row-select][aria-pressed="true"]');
  await expect(rowButtons).toHaveCount(5);
  await expect(watchlist.locator('[data-row-select][tabindex="0"]')).toHaveCount(1);

  const initialTabStop = watchlist.locator('[data-row-select][tabindex="0"]');
  const initialSymbol = await initialTabStop.getAttribute("data-symbol");
  await initialTabStop.focus();
  await page.keyboard.press("ArrowDown");
  const focusedAfterDown = await page.locator(":focus").getAttribute("data-symbol");
  expect(focusedAfterDown).not.toBe(initialSymbol);
  await expect(watchlist.locator('[data-row-select][tabindex="0"]')).toHaveCount(1);
  await expect(marketRowButton(watchlist, initialSymbol ?? "")).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await expect(page).toHaveURL(/\/$/);

  await page.keyboard.press("Home");
  await expect(page.locator(":focus")).toHaveAttribute("data-symbol", initialSymbol ?? "");
  await page.keyboard.press("End");
  const lastSymbol = await rowButtons.last().getAttribute("data-symbol");
  await expect(page.locator(":focus")).toHaveAttribute("data-symbol", lastSymbol ?? "");
  await page.keyboard.press("Enter");
  await expect(marketRowButton(watchlist, lastSymbol ?? "")).toHaveAttribute(
    "aria-pressed",
    "true"
  );

  await page.keyboard.press("ArrowUp");
  const focusedBeforeSpace = await page.locator(":focus").getAttribute("data-symbol");
  expect(focusedBeforeSpace).not.toBe(lastSymbol);
  await expect(marketRowButton(watchlist, lastSymbol ?? "")).toHaveAttribute(
    "aria-pressed",
    "true"
  );
  await page.keyboard.press("Space");
  await expect(marketRowButton(watchlist, focusedBeforeSpace ?? "")).toHaveAttribute(
    "aria-pressed",
    "true"
  );

  await page.keyboard.press("Tab");
  await expect(page.locator(":focus").locator("xpath=ancestor-or-self::*[@data-market-row]")).toHaveCount(
    0
  );
  await expect(watchlist.locator('[data-row-select][tabindex="0"]')).toHaveCount(1);
  await expect(selectedButton).toHaveCount(1);
});

test("keeps a THIN draft fixed when the dashboard selection changes to ALT", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  const contextGroup = detail.locator('details[data-detail-group="context"]');
  await contextGroup.locator("summary").click();
  await contextGroup.getByLabel("理由", { exact: true }).fill("THIN固定の下書き");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await marketRowButton(watchlist, "ALTUSDT").click();
  await expect(detail.getByRole("heading", { name: "ALT" })).toBeVisible();
  await expect(detail.getByText("保存対象を固定中")).toBeVisible();
  await expect(detail.getByText("THIN", { exact: true })).toBeVisible();
  await expect(contextGroup.getByLabel("理由", { exact: true })).toHaveValue("THIN固定の下書き");

  await contextGroup.getByRole("button", { name: "銘柄注記を保存" }).click();
  await expect(
    detail.getByText("下書きは THINUSDT に固定されています。現在の銘柄には保存できません")
  ).toBeVisible();
  await expect(contextGroup.getByLabel("理由", { exact: true })).toHaveValue("THIN固定の下書き");
});

test("clears an old Past Note save notice when a new dashboard draft starts", async ({ page }) => {
  rmSync(pastNotesDir, { recursive: true, force: true });
  generateSnapshot("basic");
  await page.goto("/");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await openDetailGroup(detail, "context");
  const contextGroup = detail.locator('details[data-detail-group="context"]');
  const noteReason = contextGroup.getByLabel("理由", { exact: true });
  await noteReason.fill("保存済み注記");
  await contextGroup.getByRole("button", { name: "銘柄注記を保存" }).click();
  await expect(contextGroup.getByRole("status")).toHaveText("銘柄注記を保存しました");

  await noteReason.fill("次の未保存注記");
  await expect(contextGroup.getByRole("status")).toHaveCount(0);
  await expect(noteReason).toHaveValue("次の未保存注記");
});

test("keeps a newer Past Note draft unsaved after deferred success", async ({
  page
}) => {
  rmSync(pastNotesDir, { recursive: true, force: true });
  generateSnapshot("basic");
  await page.goto("/");

  const newerDraftNotice = "送信時点の内容を保存しました。追加の変更は未保存です";
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });

  await openDetailGroup(detail, "context");
  const contextGroup = detail.locator('details[data-detail-group="context"]');
  const noteReason = contextGroup.getByLabel("理由", { exact: true });
  await noteReason.fill("pending note V1");
  await expectDeferredMutationState({
    page,
    endpoint: "**/api/past-notes",
    method: "POST",
    button: contextGroup.locator(".note-form > button"),
    busyLabel: "保存中",
    successStatus: contextGroup.getByRole("status").filter({ hasText: newerDraftNotice }),
    whilePending: async () => {
      await noteReason.fill("pending note V2");
    },
    afterSuccess: async () => {
      await expect
        .poll(() => {
          try {
            return JSON.parse(readFileSync(pastNotesPath, "utf-8")).notes.some(
              (note: { reason?: string }) => note.reason === "pending note V1"
            );
          } catch {
            return false;
          }
        })
        .toBe(true);
      await expect(noteReason).toHaveValue("pending note V2");
      await noteReason.fill("pending note V3");
      await expect(contextGroup.getByRole("status")).toHaveText(newerDraftNotice);
    }
  });

});

test("can record a symbol annotation from the monitoring page", async ({ page }) => {
  rmSync(pastNotesDir, { recursive: true, force: true });
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await marketRowButton(watchlist, "ALTUSDT").click();
  await page
    .getByRole("complementary", { name: "選択銘柄の詳細" })
    .getByRole("link", { name: "ALTUSDT の個別分析を開く" })
    .click();
  await expect(page).toHaveURL(/\/symbols\/ALTUSDT\?tf=15m$/);
  await expect(page.getByRole("region", { name: "主チャート" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "監視材料" })).toBeVisible();

  await page
    .getByRole("region", { name: "主チャート" })
    .getByRole("link", { name: "4h", exact: true })
    .click();
  await expect(page).toHaveURL(/\/symbols\/ALTUSDT\?tf=4h$/);

  await page.getByLabel("理由", { exact: true }).fill("個別ページ確認");
  await page.getByLabel("メモ").fill("chart first から保存");
  await page.getByRole("button", { name: "銘柄注記を保存" }).click();
  await expect(page.getByText("銘柄注記: 個別ページ確認 - chart first から保存")).toBeVisible();

  const savedNotes = JSON.parse(readFileSync(pastNotesPath, "utf-8"));
  expect(savedNotes.notes[0]).toMatchObject({
    symbol: "ALTUSDT",
    reason: "個別ページ確認",
    note: "chart first から保存"
  });

  await page
    .getByRole("region", { name: "主チャート" })
    .getByRole("link", { name: "15m", exact: true })
    .click();
  await expect(page).toHaveURL(/\/symbols\/ALTUSDT\?tf=15m$/);
  await expect(page.getByText("銘柄注記: 個別ページ確認 - chart first から保存")).toBeVisible();
});

test("can save and show a local past note for the selected symbol", async ({ page }) => {
  rmSync(pastNotesDir, { recursive: true, force: true });
  generateSnapshot("basic");
  await page.goto("/");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();

  await openDetailGroup(detail, "context");
  await detail.getByLabel("理由", { exact: true }).fill("前回急変");
  await detail.getByLabel("メモ").fill("2026-06-01に短時間で大きく動いた");
  await detail.getByRole("button", { name: "銘柄注記を保存" }).click();

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(marketRow(watchlist, "THINUSDT")).toContainText("銘柄注記");
  await expect(detail.getByText("銘柄注記: 前回急変 - 2026-06-01に短時間で大きく動いた")).toBeVisible();

  const saved = JSON.parse(readFileSync(pastNotesPath, "utf-8"));
  expect(saved.notes[0]).toMatchObject({
    symbol: "THINUSDT",
    reason: "前回急変",
    note: "2026-06-01に短時間で大きく動いた"
  });

  await page.reload();
  await expect(marketRow(watchlist, "THINUSDT")).toContainText("銘柄注記");
  await openDetailGroup(detail, "context");
  await expect(detail.getByText("銘柄注記: 前回急変 - 2026-06-01に短時間で大きく動いた")).toBeVisible();
});

test("shows an automatic past note from the current past-notes file", async ({ page }) => {
  rmSync(pastNotesDir, { recursive: true, force: true });
  mkdirSync(pastNotesDir, { recursive: true });
  writeFileSync(
    pastNotesPath,
    JSON.stringify(
      {
        notes: [
          {
            symbol: "THINUSDT",
            reason: "自動検出: 過去急変",
            observedAt: "2026-06-21T00:00:00.000Z",
            expiresAt: "2026-08-20T00:00:00.000Z",
            note: "検出日=2026-06-01 12:00 UTC, 4h変化率=+9.0%, 4h売買代金=336,000 USDT"
          }
        ]
      },
      null,
      2
    ) + "\n",
    "utf-8"
  );
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(marketRow(watchlist, "THINUSDT")).toContainText("過去急変");
  await expect(detail.getByRole("heading", { name: "THIN" })).toBeVisible();
  await openDetailGroup(detail, "context");
  await expect(
    detail.getByText(
      "銘柄注記: 自動検出: 過去急変 - 検出日=2026-06-01 12:00 UTC, 4h変化率=+9.0%, 4h売買代金=336,000 USDT"
    )
  ).toBeVisible();
});

test("can request a service snapshot refresh from the dashboard", async ({ page }) => {
  let refreshCalls = 0;
  await page.route("**/api/refresh-live", async (route) => {
    refreshCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true })
    });
  });

  generateSnapshot("basic");
  await page.goto("/");

  await page.getByRole("button", { name: "service snapshotを更新" }).click();

  await expect.poll(() => refreshCalls).toBe(1);
  await expect(page.getByRole("button", { name: "service snapshotを更新" })).toBeEnabled();
});

test("renders stale and partial data as risk states", async ({ page }) => {
  generateSnapshot("stale");
  await page.goto("/");

  await expect(page.locator(".source-banner")).toContainText("検証データ");
  await expect(page.locator(".source-banner")).toContainText("古い");
  await expect(page.locator(".source-banner")).toContainText("古いデータ");

  const categories = page.getByRole("complementary", { name: "分類" });
  await expect(categories.getByRole("button", { name: /すべて\s+2/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /注視\s+0/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /注意\s+1/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /監視除外候補\s+1/ })).toBeVisible();

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(watchlist.getByText("表示 2 / 全 2")).toBeVisible();
  await expect(marketRow(watchlist, "STALEUSDT")).toContainText("古いデータ");
  await expect(marketRow(watchlist, "PARTIALUSDT")).toContainText("一部不足");

  await categories.getByRole("button", { name: /監視除外候補\s+1/ }).click();
  await expect(marketRow(watchlist, "STALEUSDT")).toContainText("古いデータ");

  await categories.getByRole("button", { name: /注意\s+1/ }).click();
  await expect(marketRow(watchlist, "PARTIALUSDT")).toContainText("一部不足");
});

test("renders thin-spike and missing-coverage monitoring-exclusion rows", async ({ page }) => {
  generateSnapshot("thin-spike");
  await page.goto("/");

  await expect(page.locator(".source-banner")).toContainText("正常");
  await expect(page.locator(".source-banner")).toContainText("薄商い急変");

  const categories = page.getByRole("complementary", { name: "分類" });
  await expect(categories.getByRole("button", { name: /すべて\s+3/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /注視\s+1/ })).toBeVisible();
  await expect(categories.getByRole("button", { name: /監視除外候補\s+2/ })).toBeVisible();

  await categories.getByRole("button", { name: /監視除外候補\s+2/ }).click();
  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  await expect(marketRow(watchlist, "WICKUSDT")).toContainText("薄商い急変");
  await expect(marketRow(watchlist, "GAPUSDT")).toContainText("データ不足");
  await expect(marketRow(watchlist, "GAPUSDT")).toContainText("欠損");

  const detail = page.getByRole("complementary", { name: "選択銘柄の詳細" });
  await expect(detail.getByRole("heading", { name: "WICK" })).toBeVisible();
  const exclusionPanel = detail.getByRole("region", { name: "除外理由" });
  await expect(exclusionPanel.getByRole("heading", { name: "除外理由" })).toBeVisible();
  await expect(exclusionPanel.getByText("薄商い急変")).toBeVisible();
  await expect(detail.getByText("監視を続ける条件と解除条件を先に言語化する。")).toBeVisible();
});

test("renders a snapshot error instead of a broken dashboard", async ({ page }) => {
  writeFileSync(snapshotPath, "{ invalid json", "utf-8");
  await page.goto("/");

  await expect(page.getByText("スナップショットエラー")).toBeVisible();
  await expect(page.locator("main.error-shell h1")).toHaveText("データを読み込めませんでした");
});
