import { readFile } from "node:fs/promises";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { resolveMarketStatePaths } from "./market-state-paths";

export type FavoriteTarget =
  | { kind: "instrument"; id: string; version: number }
  | { kind: "reference"; id: string; referenceKey: string; originals: string[] };

export type ComparisonPin = {
  target: FavoriteTarget;
  episodeId: string | null;
  discoveredAt: number;
  snapshot: Record<string, unknown>;
};

export type SavedView = {
  id: string;
  name: string;
  view: Record<string, string | number | boolean | null>;
};

export type UserWorkspace = {
  schemaVersion: 2;
  revision: number;
  favorites: FavoriteTarget[];
  savedViews: SavedView[];
  pins: ComparisonPin[];
};

export class UserWorkspaceError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}

const EMPTY: UserWorkspace = { schemaVersion: 2, revision: 0, favorites: [], savedViews: [], pins: [] };
const MAX_BYTES = 65_536;

export function favoriteKey(target: FavoriteTarget) {
  return target.kind === "instrument"
    ? `instrument:${target.id}:${target.version}`
    : `reference:${target.id}`;
}

export function isFavoriteTarget(value: unknown): value is FavoriteTarget {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const target = value as Record<string, unknown>;
  if (typeof target.id !== "string" || !/^[A-Za-z0-9:._-]{1,160}$/.test(target.id)) return false;
  if (target.kind === "instrument") {
    return Object.keys(target).every((key) => ["kind", "id", "version"].includes(key)) &&
      Number.isSafeInteger(target.version) && Number(target.version) > 0;
  }
  return target.kind === "reference" &&
    Object.keys(target).every((key) => ["kind", "id", "referenceKey", "originals"].includes(key)) &&
    typeof target.referenceKey === "string" &&
    target.referenceKey.length > 0 && target.referenceKey.length <= 200 &&
    Array.isArray(target.originals) && target.originals.length <= 10 &&
    target.originals.every((entry) => typeof entry === "string" && entry.length <= 200);
}

export function isSavedView(value: unknown): value is SavedView {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const view = value as Partial<SavedView>;
  return typeof view.id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(view.id) &&
    typeof view.name === "string" && view.name.length > 0 && view.name.length <= 80 &&
    !!view.view && typeof view.view === "object" && !Array.isArray(view.view) &&
    Object.keys(view).every((key) => ["id", "name", "view"].includes(key)) &&
    Object.keys(view.view).length <= 30 &&
    Object.values(view.view).every((entry) => entry === null ||
      (typeof entry === "string" && entry.length <= 200) ||
      (typeof entry === "number" && Number.isFinite(entry)) ||
      typeof entry === "boolean");
}

export function isComparisonPin(value: unknown): value is ComparisonPin {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const pin = value as ComparisonPin;
  return Object.keys(pin).every(key => ["target", "episodeId", "discoveredAt", "snapshot"].includes(key)) &&
    isFavoriteTarget(pin.target) && (pin.episodeId === null ||
      typeof pin.episodeId === "string" && pin.episodeId.length > 0 && pin.episodeId.length <= 160) &&
    Number.isSafeInteger(pin.discoveredAt) && pin.discoveredAt > 0 &&
    !!pin.snapshot && typeof pin.snapshot === "object" && !Array.isArray(pin.snapshot) &&
    Buffer.byteLength(JSON.stringify(pin.snapshot)) <= 12_000;
}

function isWorkspace(value: unknown): value is UserWorkspace {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as Partial<UserWorkspace>;
  return item.schemaVersion === 2 && Number.isSafeInteger(item.revision) &&
    Number(item.revision) >= 0 && Array.isArray(item.favorites) &&
    item.favorites.length <= 200 && item.favorites.every(isFavoriteTarget) &&
    new Set(item.favorites.map(favoriteKey)).size === item.favorites.length &&
    Array.isArray(item.savedViews) && item.savedViews.length <= 20 &&
    item.savedViews.every(isSavedView) &&
    new Set(item.savedViews.map((view) => view.id)).size === item.savedViews.length &&
    Array.isArray(item.pins) && item.pins.length <= 4 && item.pins.every(isComparisonPin) &&
    new Set(item.pins.map(pin => favoriteKey(pin.target))).size === item.pins.length &&
    Object.keys(item).every((key) => ["schemaVersion", "revision", "favorites", "savedViews", "pins"].includes(key));
}

export class LocalFileUserWorkspaceRepository {
  constructor(private readonly path = resolveMarketStatePaths().userWorkspacePath) {}

  async read() {
    return await withLockFile(`${this.path}.lock`, () => this.readUnlocked());
  }

  async setFavorite(target: FavoriteTarget, enabled: boolean, expectedRevision?: number) {
    return await withLockFile(`${this.path}.lock`, async () => {
      const current = await this.readUnlocked();
      const key = favoriteKey(target);
      const previous = current.favorites.find((entry) => favoriteKey(entry) === key);
      if (enabled && previous && JSON.stringify(previous) === JSON.stringify(target)) return current;
      if (expectedRevision !== undefined && current.revision !== expectedRevision) {
        throw new UserWorkspaceError(409, "workspace_conflict");
      }
      if (enabled && previous && expectedRevision === undefined) {
        throw new UserWorkspaceError(409, "favorite_recheck_required");
      }
      if (!enabled && !previous) return current;
      const favorites = enabled
        ? [...current.favorites.filter((entry) => favoriteKey(entry) !== key), target]
        : current.favorites.filter((entry) => favoriteKey(entry) !== key);
      return await this.write({ ...current, revision: current.revision + 1, favorites });
    });
  }

  async setPin(pin: ComparisonPin, enabled: boolean, expectedRevision: number) {
    if (!isComparisonPin(pin)) throw new UserWorkspaceError(400, "invalid_comparison_pin");
    return await withLockFile(`${this.path}.lock`, async () => {
      const current = await this.readUnlocked();
      const key = favoriteKey(pin.target);
      const previous = current.pins.find(entry => favoriteKey(entry.target) === key);
      if (enabled && previous && JSON.stringify(previous) === JSON.stringify(pin)) return current;
      if (!enabled && !previous) return current;
      if (current.revision !== expectedRevision) throw new UserWorkspaceError(409, "workspace_conflict");
      if (enabled && previous) {
        throw new UserWorkspaceError(409, "pin_target_recheck_required");
      }
      const pins = enabled ? [...current.pins, pin]
        : current.pins.filter(entry => favoriteKey(entry.target) !== key);
      return await this.write({ ...current, revision: current.revision + 1, pins });
    });
  }

  async saveView(view: SavedView, expectedRevision: number) {
    if (!isSavedView(view)) throw new UserWorkspaceError(400, "invalid_saved_view");
    return await withLockFile(`${this.path}.lock`, async () => {
      const current = await this.readUnlocked();
      if (current.revision !== expectedRevision) throw new UserWorkspaceError(409, "workspace_conflict");
      const savedViews = [...current.savedViews.filter((entry) => entry.id !== view.id), view];
      return await this.write({ ...current, revision: current.revision + 1, savedViews });
    });
  }

  async removeView(id: string, expectedRevision: number) {
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new UserWorkspaceError(400, "invalid_saved_view_id");
    return await withLockFile(`${this.path}.lock`, async () => {
      const current = await this.readUnlocked();
      if (current.revision !== expectedRevision) throw new UserWorkspaceError(409, "workspace_conflict");
      const savedViews = current.savedViews.filter((entry) => entry.id !== id);
      return await this.write({ ...current, revision: current.revision + 1, savedViews });
    });
  }

  private async readUnlocked(): Promise<UserWorkspace> {
    let bytes: Buffer;
    try {
      bytes = await readFile(this.path);
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code === "ENOENT") return structuredClone(EMPTY);
      throw new UserWorkspaceError(500, "workspace_unavailable");
    }
    if (bytes.byteLength > MAX_BYTES) throw new UserWorkspaceError(500, "workspace_invalid");
    let value: unknown;
    try { value = JSON.parse(bytes.toString("utf-8")); }
    catch { throw new UserWorkspaceError(500, "workspace_invalid"); }
    if (value && typeof value === "object" && !Array.isArray(value) &&
        (value as { schemaVersion?: number }).schemaVersion === 1 &&
        Object.keys(value).every(key => ["schemaVersion", "revision", "favorites", "savedViews"].includes(key))) {
      value = { ...value, schemaVersion: 2, pins: [] };
    }
    if (!isWorkspace(value)) throw new UserWorkspaceError(500, "workspace_invalid");
    return value;
  }

  private async write(next: UserWorkspace) {
    if (!isWorkspace(next)) throw new UserWorkspaceError(413, "workspace_limit");
    if (Buffer.byteLength(`${JSON.stringify(next, null, 2)}\n`) > MAX_BYTES) {
      throw new UserWorkspaceError(413, "workspace_limit");
    }
    await writeJsonFileAtomic(this.path, next);
    return next;
  }
}

export function createUserWorkspaceRepository() {
  return new LocalFileUserWorkspaceRepository();
}
