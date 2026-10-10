import { readFile } from "node:fs/promises";
import Ajv2020, { type ValidateFunction } from "ajv/dist/2020";
import marketChartSchema from "../../../../../schemas/market-chart.schema.json";
import marketServiceStateSchema from "../../../../../schemas/service-state.schema.json";
import selectedMarketSchema from "../../../../../schemas/selected-market.schema.json";
import universeSnapshotSchema from "../../../../../schemas/universe-snapshot.schema.json";
import type { MarketChartArtifact } from "$lib/generated/market-chart";
import type { MarketServiceStateArtifact } from "$lib/generated/service-state";
import type { SelectedMarketArtifact } from "$lib/generated/selected-market";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { resolveMarketStatePaths, type MarketStatePaths } from "./market-state-paths";

export type MarketArtifactBundle = {
  universe: UniverseSnapshotArtifact;
  chart: MarketChartArtifact;
  selected: SelectedMarketArtifact;
  service: MarketServiceStateArtifact;
};

export interface MarketArtifactRepository {
  latest(): Promise<MarketArtifactBundle>;
  latestUniverse?(): Promise<UniverseSnapshotArtifact>;
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
ajv.addFormat("date-time", {
  type: "string",
  validate: (value: string) =>
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    Number.isFinite(Date.parse(value))
});
const validators = {
  universe: ajv.compile(universeSnapshotSchema),
  chart: ajv.compile(marketChartSchema),
  selected: ajv.compile(selectedMarketSchema),
  service: ajv.compile(marketServiceStateSchema)
};
const MAX_UNIVERSE_READ_ATTEMPTS = 5;
const UNIVERSE_READ_RETRY_DELAY_MS = 50;
const MAX_PUBLICATION_RETRY_ATTEMPTS = 4;
const PUBLICATION_RETRY_DELAY_MS = 50;

export class LocalFileMarketArtifactRepository implements MarketArtifactRepository {
  constructor(
    private readonly paths: MarketStatePaths = resolveMarketStatePaths(),
    private readonly now = () => new Date()
  ) {}

  async latest(): Promise<MarketArtifactBundle> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const serviceBefore = await readArtifact<MarketServiceStateArtifact>(
        this.paths.serviceStatePath,
        "service-state",
        validators.service
      );
      assertFresh(serviceBefore.generatedAt, this.now(), "service-state");
      const [universe, chart, selected] = await Promise.all([
        readArtifact<UniverseSnapshotArtifact>(
          this.paths.universeSnapshotPath,
          "universe-snapshot",
          validators.universe
        ),
        readArtifact<MarketChartArtifact>(
          this.paths.marketChartPath,
          "market-chart",
          validators.chart
        ),
        readArtifact<SelectedMarketArtifact>(
          this.paths.selectedMarketPath,
          "selected-market",
          validators.selected
        )
      ]);
      const serviceAfter = await readArtifact<MarketServiceStateArtifact>(
        this.paths.serviceStatePath,
        "service-state",
        validators.service
      );

      if (serviceBefore.generatedAt !== serviceAfter.generatedAt) continue;
      assertFresh(serviceAfter.generatedAt, this.now(), "service-state");
      assertFresh(universe.generatedAt, this.now(), "universe-snapshot");
      assertFresh(chart.generatedAt, this.now(), "market-chart");
      assertFresh(
        selected.generatedAt,
        this.now(),
        "selected-market",
        MAX_SELECTED_MARKET_AGE_MS
      );
      if (!isPublishedGeneration(serviceAfter, { universe, chart, selected })) {
        if (attempt === 0) continue;
        throw new Error("market artifacts changed while being read");
      }
      return { universe, chart, selected, service: serviceAfter };
    }
    throw new Error("market artifacts changed while being read");
  }

  async latestUniverse(): Promise<UniverseSnapshotArtifact> {
    for (let attempt = 0; attempt < MAX_UNIVERSE_READ_ATTEMPTS; attempt += 1) {
      if (attempt > 0) await waitForUniverseReadRetry();
      const serviceBefore = await readArtifact<MarketServiceStateArtifact>(
        this.paths.serviceStatePath,
        "service-state",
        validators.service
      );
      assertFresh(serviceBefore.generatedAt, this.now(), "service-state");
      const universe = await readArtifact<UniverseSnapshotArtifact>(
        this.paths.universeSnapshotPath,
        "universe-snapshot",
        validators.universe
      );
      const serviceAfter = await readArtifact<MarketServiceStateArtifact>(
        this.paths.serviceStatePath,
        "service-state",
        validators.service
      );

      if (serviceBefore.generatedAt !== serviceAfter.generatedAt) continue;
      assertFresh(serviceAfter.generatedAt, this.now(), "service-state");
      assertFresh(universe.generatedAt, this.now(), "universe-snapshot");
      const universeState = serviceAfter.artifacts.find(
        (artifact) => artifact.name === "universe-snapshot.json"
      );
      if (universeState?.status === "ready" && universeState.generatedAt === universe.generatedAt) {
        return universe;
      }
    }
    throw new Error("market universe changed while being read");
  }
}

const MAX_ARTIFACT_AGE_MS = 120_000;
const MAX_SELECTED_MARKET_AGE_MS = 15_000;

function assertFresh(
  generatedAt: string,
  now: Date,
  name: string,
  maxAgeMs = MAX_ARTIFACT_AGE_MS
) {
  const ageMs = now.getTime() - Date.parse(generatedAt);
  if (!Number.isFinite(ageMs) || Math.abs(ageMs) > maxAgeMs) {
    throw new Error(`${name} is stale`);
  }
}

function waitForUniverseReadRetry(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, UNIVERSE_READ_RETRY_DELAY_MS));
}

function waitForPublicationRetry(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, PUBLICATION_RETRY_DELAY_MS));
}

export function createMarketArtifactRepository(): MarketArtifactRepository {
  const source = new LocalFileMarketArtifactRepository();
  return {
    latest: () => retryArtifactPublication(() => source.latest()),
    latestUniverse: () => source.latestUniverse()
  };
}

export async function retryArtifactPublication<T>(read: () => Promise<T>): Promise<T> {
  for (let attempt = 0; attempt < MAX_PUBLICATION_RETRY_ATTEMPTS; attempt += 1) {
    try {
      return await read();
    } catch (cause) {
      const isPublicationMismatch = cause instanceof Error &&
        cause.message === "market artifacts changed while being read";
      if (!isPublicationMismatch || attempt === MAX_PUBLICATION_RETRY_ATTEMPTS - 1) {
        throw cause;
      }
      await waitForPublicationRetry();
    }
  }
  throw new Error("market artifact publication retry exhausted");
}

async function readArtifact<T>(path: string, name: string, validate: ValidateFunction): Promise<T> {
  let payload: unknown;
  try {
    payload = JSON.parse(await readFile(path, "utf-8"));
  } catch (cause) {
    throw new Error(`${name} unavailable`, { cause });
  }
  if (!validate(payload)) {
    throw new Error(`${name} invalid: ${ajv.errorsText(validate.errors)}`);
  }
  return payload as T;
}

function isPublishedGeneration(
  service: MarketServiceStateArtifact,
  artifacts: Pick<MarketArtifactBundle, "universe" | "chart" | "selected">
) {
  const required = new Map([
    ["universe-snapshot.json", artifacts.universe.generatedAt],
    ["market-chart.json", artifacts.chart.generatedAt],
    ["selected-market.json", artifacts.selected.generatedAt]
  ]);
  for (const [name, generatedAt] of required) {
    const fileState = service.artifacts.find((item) => item.name === name);
    if (!fileState || fileState.status !== "ready" || fileState.generatedAt !== generatedAt) {
      return false;
    }
  }
  return true;
}
