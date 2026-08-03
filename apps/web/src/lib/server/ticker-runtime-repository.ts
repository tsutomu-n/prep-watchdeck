import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { resolveStatePaths } from "./state-paths";

export type TickerRuntimeUpdate = [symbol: string, lastPrice: number, ts: number];

export type TickerRuntimeBatch = {
  schemaVersion: 1;
  sequence: number;
  asOf: number;
  full: boolean;
  updates: TickerRuntimeUpdate[];
};

type TickerRuntimeFile = {
  schemaVersion: 1;
  sequence: number;
  asOf: number;
  fullUpdates: TickerRuntimeUpdate[];
  deltaUpdates: TickerRuntimeUpdate[];
};

type TickerRuntimeCacheEntry = {
  size: bigint;
  mtimeNs: bigint;
  runtime: TickerRuntimeFile;
};

export interface TickerRuntimeRepository {
  batchAfter(afterSequence: number): Promise<TickerRuntimeBatch | undefined>;
}

const safeSymbolPattern = /^[A-Z0-9_-]+$/;
const tickerRuntimeCache = new Map<string, TickerRuntimeCacheEntry>();

export class LocalFileTickerRuntimeRepository implements TickerRuntimeRepository {
  constructor(private readonly runtimePath = defaultTickerRuntimePath()) {}

  async batchAfter(afterSequence: number): Promise<TickerRuntimeBatch | undefined> {
    const resolvedPath = resolve(this.runtimePath);
    const metadata = await stat(resolvedPath, { bigint: true }).catch((cause) => {
      if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
        return null;
      }
      throw cause;
    });
    if (metadata === null) {
      tickerRuntimeCache.delete(resolvedPath);
      return undefined;
    }

    const cached = tickerRuntimeCache.get(resolvedPath);
    let runtime: TickerRuntimeFile;
    if (cached && cached.size === metadata.size && cached.mtimeNs === metadata.mtimeNs) {
      runtime = cached.runtime;
    } else {
      runtime = parseTickerRuntime(await readFile(resolvedPath, "utf-8"));
      tickerRuntimeCache.set(resolvedPath, {
        size: metadata.size,
        mtimeNs: metadata.mtimeNs,
        runtime
      });
    }
    if (afterSequence === runtime.sequence) return undefined;
    const useDelta = afterSequence > 0 && afterSequence === runtime.sequence - 1;
    return {
      schemaVersion: 1,
      sequence: runtime.sequence,
      asOf: runtime.asOf,
      full: !useDelta,
      updates: useDelta ? runtime.deltaUpdates : runtime.fullUpdates
    };
  }
}

export function createTickerRuntimeRepository(): TickerRuntimeRepository {
  return new LocalFileTickerRuntimeRepository();
}

function parseTickerRuntime(raw: string): TickerRuntimeFile {
  let candidate: unknown;
  try {
    candidate = JSON.parse(raw);
  } catch {
    throw new Error("invalid ticker runtime");
  }
  if (
    !isRecord(candidate) ||
    candidate.schemaVersion !== 1 ||
    !isPositiveInteger(candidate.sequence) ||
    !isNonNegativeInteger(candidate.asOf) ||
    !Array.isArray(candidate.fullUpdates) ||
    !Array.isArray(candidate.deltaUpdates)
  ) {
    throw new Error("invalid ticker runtime");
  }

  const fullUpdates = validateUpdates(candidate.fullUpdates);
  const deltaUpdates = validateUpdates(candidate.deltaUpdates);
  const fullBySymbol = new Map(fullUpdates.map((update) => [update[0], update]));
  for (const delta of deltaUpdates) {
    const full = fullBySymbol.get(delta[0]);
    if (!full || full[1] !== delta[1] || full[2] !== delta[2]) {
      throw new Error("invalid ticker runtime");
    }
  }
  return {
    schemaVersion: 1,
    sequence: candidate.sequence,
    asOf: candidate.asOf,
    fullUpdates,
    deltaUpdates
  };
}

function validateUpdates(candidates: unknown[]): TickerRuntimeUpdate[] {
  const symbols = new Set<string>();
  return candidates.map((candidate) => {
    if (
      !Array.isArray(candidate) ||
      candidate.length !== 3 ||
      typeof candidate[0] !== "string" ||
      !safeSymbolPattern.test(candidate[0]) ||
      !isPositiveNumber(candidate[1]) ||
      !isPositiveInteger(candidate[2]) ||
      symbols.has(candidate[0])
    ) {
      throw new Error("invalid ticker runtime");
    }
    symbols.add(candidate[0]);
    return [candidate[0], candidate[1], candidate[2]];
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function defaultTickerRuntimePath() {
  return resolveStatePaths().tickerRuntimePath;
}
