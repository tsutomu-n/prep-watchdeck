import { writeFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "vitest";
import type { MarketArtifactBundle } from "./market-artifact-repository";
import { LocalFileMarketArtifactRepository } from "./market-artifact-repository";
import { isLocalhostRequest } from "./localhost-request";
import { resolveMarketStatePaths } from "./market-state-paths";
import { LocalFileSelectionCommandRepository } from "./selection-command-repository";

describe("market artifact and local selection repositories", () => {
  test("accepts one coherent four-file generation and rejects an invalid artifact", async () => {
    const root = await mkdtemp(join(tmpdir(), "watchdeck-market-artifacts-"));
    const paths = resolveMarketStatePaths({ PREP_WATCHDECK_MARKET_STATE_DIR: root });
    const bundle = fixtureBundle();
    try {
      await writeArtifacts(paths, bundle);
      const repository = new LocalFileMarketArtifactRepository(
        paths,
        () => new Date("2026-08-14T12:00:10Z")
      );
      await expect(repository.latest()).resolves.toEqual(bundle);

      await writeFile(paths.universeSnapshotPath, JSON.stringify({ schemaVersion: 1 }), "utf-8");
      await expect(repository.latest()).rejects.toThrow(/universe-snapshot invalid/);

      await writeArtifacts(paths, bundle);
      const staleSelected = new LocalFileMarketArtifactRepository(
        paths,
        () => new Date("2026-08-14T12:00:16Z")
      );
      await expect(staleSelected.latest()).rejects.toThrow(/selected-market is stale/);

      const stale = new LocalFileMarketArtifactRepository(
        paths,
        () => new Date("2026-08-14T12:02:01Z")
      );
      await expect(stale.latest()).rejects.toThrow(/service-state is stale/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("retries one in-progress published generation before returning a coherent bundle", async () => {
    const root = await mkdtemp(join(tmpdir(), "watchdeck-market-generation-race-"));
    const paths = resolveMarketStatePaths({ PREP_WATCHDECK_MARKET_STATE_DIR: root });
    const initial = fixtureBundle();
    const refreshed = structuredClone(initial);
    refreshed.selected.generatedAt = "2026-08-14T12:00:05Z";
    refreshed.service.generatedAt = "2026-08-14T12:00:05Z";
    const selectedState = refreshed.service.artifacts.find(
      (item) => item.name === "selected-market.json"
    );
    if (!selectedState) throw new Error("selected artifact state missing from fixture");
    selectedState.generatedAt = refreshed.selected.generatedAt;
    const serviceState = refreshed.service.artifacts.find(
      (item) => item.name === "service-state.json"
    );
    if (!serviceState) throw new Error("service artifact state missing from fixture");
    serviceState.generatedAt = refreshed.service.generatedAt;
    let nowCalls = 0;
    try {
      await writeArtifacts(paths, initial);
      const repository = new LocalFileMarketArtifactRepository(paths, () => {
        nowCalls += 1;
        if (nowCalls === 1) {
          writeFileSync(paths.selectedMarketPath, JSON.stringify(refreshed.selected), "utf-8");
        } else if (nowCalls === 2) {
          writeFileSync(paths.serviceStatePath, JSON.stringify(refreshed.service), "utf-8");
        }
        return new Date("2026-08-14T12:00:10Z");
      });

      await expect(repository.latest()).resolves.toEqual(refreshed);
      expect(nowCalls).toBeGreaterThan(2);

      const persistentlyMismatched = structuredClone(refreshed.selected);
      persistentlyMismatched.generatedAt = "2026-08-14T12:00:06Z";
      await writeFile(
        paths.selectedMarketPath,
        JSON.stringify(persistentlyMismatched),
        "utf-8"
      );
      const mismatchedRepository = new LocalFileMarketArtifactRepository(
        paths,
        () => new Date("2026-08-14T12:00:10Z")
      );
      await expect(mismatchedRepository.latest()).rejects.toThrow(
        /market artifacts changed while being read/
      );
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("writes an atomic eligible command and preserves requestedAt on heartbeat", async () => {
    const root = await mkdtemp(join(tmpdir(), "watchdeck-selection-command-"));
    const paths = resolveMarketStatePaths({ PREP_WATCHDECK_MARKET_STATE_DIR: root });
    const bundle = fixtureBundle();
    let now = new Date("2026-08-14T12:00:00.000Z");
    const repository = new LocalFileSelectionCommandRepository(
      paths.selectionCommandPath,
      { latest: async () => bundle },
      () => now
    );
    try {
      const first = await repository.write("crypto:BTC:linear-perp", "bitget:BTCUSDT");
      now = new Date("2026-08-14T12:05:00.000Z");
      const heartbeat = await repository.write("crypto:BTC:linear-perp", "bitget:BTCUSDT");
      expect(heartbeat.requestedAt).toBe(first.requestedAt);
      expect(heartbeat.heartbeatAt).toBe("2026-08-14T12:05:00.000Z");
      await expect(repository.write("crypto:ETH:linear-perp", "bitget:BTCUSDT")).rejects.toThrow(
        /not an active grouped instrument/
      );
      expect(JSON.parse(await readFile(paths.selectionCommandPath, "utf-8"))).toEqual(heartbeat);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  test("requires both a localhost Host and a loopback client address", () => {
    expect(localRequest("http://localhost/api/selection", "127.0.0.1")).toBe(true);
    expect(localRequest("http://[::1]/api/selection", "::ffff:127.0.0.1")).toBe(true);
    expect(localRequest("http://localhost/api/selection", "203.0.113.8")).toBe(false);
    expect(localRequest("https://example.com/api/selection", "127.0.0.1")).toBe(false);
  });
});

function localRequest(url: string, address: string) {
  return isLocalhostRequest({ url: new URL(url), getClientAddress: () => address });
}

async function writeArtifacts(
  paths: ReturnType<typeof resolveMarketStatePaths>,
  bundle: MarketArtifactBundle
) {
  await mkdir(paths.artifactDir, { recursive: true });
  await Promise.all([
    writeFile(paths.universeSnapshotPath, JSON.stringify(bundle.universe), "utf-8"),
    writeFile(paths.marketChartPath, JSON.stringify(bundle.chart), "utf-8"),
    writeFile(paths.selectedMarketPath, JSON.stringify(bundle.selected), "utf-8"),
    writeFile(paths.serviceStatePath, JSON.stringify(bundle.service), "utf-8")
  ]);
}

function fixtureBundle(): MarketArtifactBundle {
  const generatedAt = "2026-08-14T12:00:00Z";
  return {
    universe: {
      schemaVersion: 1,
      generatedAt,
      status: "ready",
      qualityReasons: [],
      parityAssumption: {
        code: "usd_usdc_usdt_reference_only",
        appliedTo: "reference_mark_median_only",
        statement: "reference only"
      },
      items: [
        {
          venueInstrumentId: "bitget:BTCUSDT",
          venueInstrumentVersionId: 1,
          groupId: "crypto:BTC:linear-perp",
          mappingMethod: "exact_base_heuristic",
          venue: "bitget",
          sourceSymbol: "BTCUSDT",
          baseAsset: "BTC",
          quoteAsset: "USDT",
          settleAsset: "USDT",
          collateralAsset: "USDT",
          active: true,
          marketType: "linear_perpetual",
          executionModel: "clob",
          catalog: {
            sourceKind: "native_rest",
            endpoint: "/api/v2/mix/market/contracts",
            documentationUrl: null,
            payloadHash: "catalog-hash",
            observedAt: generatedAt,
            sourceAt: null
          },
          quality: "ready",
          qualityReasons: [],
          ageSeconds: 1,
          collectorRunId: "run-1",
          cycleAt: generatedAt,
          observedAt: generatedAt,
          sourceAt: null,
          sourcePayloadHash: "l1-hash",
          errorCode: null,
          markPrice: 100000,
          referencePrice: 100001,
          referencePriceKind: "index",
          bestBid: 99999,
          bestAsk: 100001,
          fundingRateRaw: 0.0001,
          fundingIntervalSeconds: 28800,
          fundingRatePerHour: 0.0000125,
          nextFundingAt: generatedAt,
          openInterestRaw: 10,
          openInterestRawUnit: "base",
          openInterestBase: 10,
          openInterestNotional: 1000000,
          volume24hRaw: 2000000,
          volume24hUnit: "quote",
          referenceMarkMedian: {
            status: "ready",
            value: 100000,
            venueCount: 2,
            venues: ["bitget", "hyperliquid"],
            cycleAt: generatedAt,
            maxAgeSeconds: 1,
            skewSeconds: 0,
            unavailableReason: null,
            parityAssumptionCode: "usd_usdc_usdt_reference_only"
          }
        }
      ]
    },
    chart: {
      schemaVersion: 1,
      generatedAt,
      status: "ready",
      qualityReasons: [],
      venueInstrumentId: "bitget:BTCUSDT",
      timeframes: []
    },
    selected: {
      schemaVersion: 1,
      generatedAt,
      status: "unavailable",
      qualityReasons: ["no_active_selection"],
      disclaimers: {
        includesFees: false,
        predictsFutureImpact: false,
        confirmsOrderAvailability: false,
        statement: "reference only"
      },
      selection: null
    },
    service: {
      schemaVersion: 1,
      generatedAt,
      status: "ready",
      qualityReasons: [],
      collectors: [],
      catalog: {
        status: "ready",
        latestAt: generatedAt,
        ageSeconds: 1,
        maxAgeSeconds: 1800,
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
        { name: "universe-snapshot.json", status: "ready", generatedAt, errorCode: null },
        { name: "market-chart.json", status: "ready", generatedAt, errorCode: null },
        { name: "selected-market.json", status: "ready", generatedAt, errorCode: null },
        { name: "service-state.json", status: "ready", generatedAt, errorCode: null }
      ]
    }
  };
}
