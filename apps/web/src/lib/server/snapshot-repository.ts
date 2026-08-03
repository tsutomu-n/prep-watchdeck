import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import schema from "../../../../../schemas/scanner-snapshot.schema.json";
import type { PrepWatchdeckScannerSnapshot, ScannerRowDTO } from "$lib/generated/scanner-snapshot";
import { resolveStatePaths } from "./state-paths";

type RankingValue = { symbol: string; value: number };
type RankingTree = {
  timeframes?: Record<string, Record<string, RankingValue[]>>;
};
type SnapshotCacheEntry = {
  size: bigint;
  mtimeNs: bigint;
  snapshot: PrepWatchdeckScannerSnapshot;
};

export interface SnapshotRepository {
  latest(): Promise<PrepWatchdeckScannerSnapshot>;
  summary(): Promise<PrepWatchdeckScannerSnapshot["summary"]>;
  rankings(tf: string, metric: string): Promise<unknown>;
  symbols(category?: string): Promise<ScannerRowDTO[]>;
  symbol(symbol: string): Promise<ScannerRowDTO | undefined>;
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateSnapshot = ajv.compile(schema);
const snapshotCache = new Map<string, SnapshotCacheEntry>();

export class LocalFileSnapshotRepository implements SnapshotRepository {
  constructor(private readonly snapshotPath = defaultSnapshotPath()) {}

  async latest(): Promise<PrepWatchdeckScannerSnapshot> {
    const resolvedPath = resolve(this.snapshotPath);
    const metadata = await stat(resolvedPath, { bigint: true });
    const cached = snapshotCache.get(resolvedPath);
    if (cached && cached.size === metadata.size && cached.mtimeNs === metadata.mtimeNs) {
      return cached.snapshot;
    }

    const raw = await readFile(resolvedPath, "utf-8");
    const payload: unknown = JSON.parse(raw);
    if (!validateSnapshot(payload)) {
      const details = ajv.errorsText(validateSnapshot.errors);
      throw new Error(`invalid scanner snapshot: ${details}`);
    }
    const snapshot = payload as unknown as PrepWatchdeckScannerSnapshot;
    snapshotCache.set(resolvedPath, {
      size: metadata.size,
      mtimeNs: metadata.mtimeNs,
      snapshot
    });
    return snapshot;
  }

  async summary() {
    return (await this.latest()).summary;
  }

  async rankings(tf: string, metric: string) {
    const snapshot = await this.latest();
    const rankings = snapshot.rankings as RankingTree | undefined;
    return rankings?.timeframes?.[tf]?.[metric] ?? [];
  }

  async symbols(category?: string) {
    const snapshot = await this.latest();
    const rows: ScannerRowDTO[] = snapshot.rows ?? [];
    return category ? rows.filter((row) => row.category === category) : rows;
  }

  async symbol(symbol: string) {
    const rows = await this.symbols();
    return rows.find((row) => row.symbol === symbol);
  }
}

export function createSnapshotRepository(): SnapshotRepository {
  return new LocalFileSnapshotRepository();
}

function defaultSnapshotPath() {
  return resolveStatePaths().snapshotPath;
}
