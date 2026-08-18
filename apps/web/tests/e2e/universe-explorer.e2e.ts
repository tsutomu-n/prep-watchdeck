import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { expect, test } from "@playwright/test";
import type { MarketChartArtifact } from "../../src/lib/generated/market-chart";
import type { SelectedMarketArtifact } from "../../src/lib/generated/selected-market";
import type { MarketServiceStateArtifact } from "../../src/lib/generated/service-state";
import type {
  UniverseInstrumentArtifact,
  UniverseSnapshotArtifact
} from "../../src/lib/generated/universe-snapshot";

const runtimeRoot = resolve(process.cwd(), "../../var/tmp/e2e/runtime");
const artifactRoot = resolve(runtimeRoot, "artifacts");
const selectionPath = resolve(runtimeRoot, "control", "selection.json");

test.beforeEach(async () => {
  await rm(selectionPath, { force: true });
  await rm(`${selectionPath}.lock`, { force: true });
  await publishArtifacts(new Date());
});

test.afterEach(async () => {
  await rm(runtimeRoot, { recursive: true, force: true });
});

test("Universe Explorerの主要な監視flowと品質表示を操作できる", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Perp Universe Explorer" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Instrument Universe" })).toBeVisible();
  await expect(page.getByText("3 / 3", { exact: true })).toBeVisible();
  await expect(page.getByText("最終検証", { exact: true })).toBeVisible();
  await expect(page.getByText("2 Venue", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("単独", { exact: true }).first()).toBeVisible();

  const inspector = page.getByRole("complementary");
  await expect(inspector.getByRole("heading", { name: "参考mark中央値" })).toBeVisible();
  await expect(inspector.getByText(/Parity仮定・reference only/)).toBeVisible();
  await expect(
    inspector.getByText("USD、USDC、USDTは参考中央値だけ等価扱い", { exact: true })
  ).toBeVisible();
  await expect(inspector.getByRole("heading", { name: "Venue L1" })).toBeVisible();
  await expect(inspector.getByText("Quote", { exact: true })).toBeVisible();
  await expect(inspector.getByText("Collateral", { exact: true })).toBeVisible();

  const selectedMarket = page.getByRole("region", { name: "選択groupの板・約定" });
  await expect(selectedMarket.getByText("最大20段 / 直近100件", { exact: true })).toBeVisible();
  await expect(selectedMarket.getByText(/手数料を含まず、将来impactを予測せず/)).toBeVisible();
  await expect(
    selectedMarket.getByRole("columnheader", { name: "板上概算" }).first()
  ).toBeVisible();
  await expect(
    selectedMarket.getByRole("rowheader", { name: "$100", exact: true }).first()
  ).toBeVisible();
  await expect(
    selectedMarket.getByRole("rowheader", { name: "$500", exact: true }).first()
  ).toBeVisible();
  await expect(
    selectedMarket.getByRole("rowheader", { name: "$1,000", exact: true }).first()
  ).toBeVisible();
  await expect(selectedMarket.getByText("板 2 bid / 2 ask", { exact: true }).first()).toBeVisible();
  await expect(selectedMarket.getByText("直近約定 1件", { exact: true })).toBeVisible();

  const theme = page.getByLabel("配色", { exact: true });
  const font = page.getByLabel("フォント", { exact: true });
  await expect(theme).toBeVisible();
  await expect(font).toBeVisible();
  await theme.selectOption("paper-ledger");
  await font.selectOption("terminal");
  await expect(page.locator("html")).toHaveAttribute("data-color-scheme", "paper-ledger");
  await expect(page.locator("html")).toHaveAttribute("data-font-scheme", "terminal");

  const search = page.getByLabel("検索", { exact: true });
  await search.fill("ETH");
  await expect(page.getByRole("button", { name: "ETH bitgetを詳細表示" })).toBeVisible();
  await expect(page.getByRole("button", { name: "BTC bitgetを詳細表示" })).toHaveCount(0);
  await search.clear();

  await page.getByRole("button", { name: "BTC hyperliquidを詳細表示" }).click();
  await expect(page.getByText("詳細データを要求しました", { exact: true })).toBeVisible();
  await expect
    .poll(async () => (await readSelectionCommand())?.venueInstrumentId ?? null)
    .toBe("hyperliquid:BTC");

  const command = await readSelectionCommand();
  expect(command).toMatchObject({
    schemaVersion: 1,
    groupId: "crypto:BTC:linear-perp",
    venueInstrumentId: "hyperliquid:BTC"
  });
  expect(Object.keys(command ?? {}).sort()).toEqual([
    "groupId",
    "heartbeatAt",
    "requestedAt",
    "schemaVersion",
    "venueInstrumentId"
  ]);

  await rm(resolve(artifactRoot, "service-state.json"), { force: true });
  await expect(page.getByText("更新停止", { exact: true })).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText(/最後に検証できたsnapshotです/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Instrument Universe" })).toBeVisible();

  const horizontalOverflow = await page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return root.scrollWidth - root.clientWidth;
  });
  expect(horizontalOverflow).toBeLessThanOrEqual(1);
});

async function publishArtifacts(now: Date) {
  const generatedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + 5 * 60_000).toISOString();
  const universe: UniverseSnapshotArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
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
          sourceAt: generatedAt,
          receivedAt: generatedAt
        }
      ]
    }
  };
  const service: MarketServiceStateArtifact = {
    schemaVersion: 1,
    generatedAt,
    status: "ready",
    qualityReasons: [],
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

async function readSelectionCommand(): Promise<Record<string, unknown> | null> {
  try {
    return JSON.parse(await readFile(selectionPath, "utf-8")) as Record<string, unknown>;
  } catch {
    return null;
  }
}
