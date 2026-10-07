import { readFile } from "node:fs/promises";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { createMarketArtifactRepository, type MarketArtifactRepository } from "./market-artifact-repository";
import { resolveMarketStatePaths } from "./market-state-paths";
import { selectionUnavailableReason } from "$lib/market/selection-eligibility";

const TTL_MS = 15 * 60_000;

export type SelectionCommand = {
  schemaVersion: 1;
  groupId: string | null;
  venueInstrumentVersionId?: number;
  venueInstrumentId: string;
  requestedAt: string;
  heartbeatAt: string;
};

export class SelectionError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}

export class LocalFileSelectionCommandRepository {
  constructor(
    private readonly path = resolveMarketStatePaths().selectionCommandPath,
    private readonly artifacts: MarketArtifactRepository = createMarketArtifactRepository(),
    private readonly now = () => new Date()
  ) {}

  async execute(command: {
    action: "select" | "heartbeat";
    groupId: string | null;
    venueInstrumentId: string;
    venueInstrumentVersionId: number;
    expectedRequestedAt?: string;
  }): Promise<SelectionCommand> {
    const { universe } = await this.artifacts.latest();
    assertEligibleSelection(universe, command);
    return await withLockFile(`${this.path}.lock`, async () => {
      const previous = await this.readCurrent();
      // Eligibility is checked again under the file lock, before any replacement.
      const latest = (await this.artifacts.latest()).universe;
      assertEligibleSelection(latest, command);
      const nowMs = this.now().getTime();
      const now = new Date(nowMs).toISOString();
      if (previous && !validTime(previous.requestedAt, nowMs)) {
        throw new SelectionError(409, "selection_clock_not_advanced");
      }
      if (command.action === "heartbeat") {
        if (!previous || previous.groupId !== command.groupId ||
            previous.venueInstrumentId !== command.venueInstrumentId ||
            (command.groupId === null && previous.venueInstrumentVersionId !== command.venueInstrumentVersionId) ||
            previous.requestedAt !== command.expectedRequestedAt ||
            !validTime(previous.heartbeatAt, nowMs) ||
            nowMs - Date.parse(previous.heartbeatAt) >= TTL_MS) {
          throw new SelectionError(409, "selection_changed");
        }
        const next = { ...previous, heartbeatAt: now };
        await writeJsonFileAtomic(this.path, next);
        return next;
      }
      const same = previous?.groupId === command.groupId &&
        previous.venueInstrumentId === command.venueInstrumentId &&
        (command.groupId !== null || previous.venueInstrumentVersionId === command.venueInstrumentVersionId) &&
        validTime(previous.heartbeatAt, nowMs) &&
        nowMs - Date.parse(previous.heartbeatAt) < TTL_MS;
      if (same && previous) {
        const next = { ...previous, heartbeatAt: now };
        await writeJsonFileAtomic(this.path, next);
        return next;
      }
      if (previous && validTime(previous.requestedAt, nowMs) &&
          Date.parse(previous.requestedAt) >= nowMs) {
        throw new SelectionError(409, "selection_clock_not_advanced");
      }
      const next: SelectionCommand = {
        schemaVersion: 1,
        groupId: command.groupId,
        venueInstrumentId: command.venueInstrumentId,
        ...(command.groupId === null ? { venueInstrumentVersionId: command.venueInstrumentVersionId } : {}),
        requestedAt: now,
        heartbeatAt: now
      };
      await writeJsonFileAtomic(this.path, next);
      return next;
    });
  }

  private async readCurrent(): Promise<SelectionCommand | null> {
    let text: string;
    try {
      text = await readFile(this.path, "utf-8");
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code === "ENOENT") return null;
      throw new SelectionError(500, "selection_unavailable");
    }
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch {
      throw new SelectionError(500, "selection_corrupt");
    }
    if (!isSelectionCommand(value)) throw new SelectionError(500, "selection_corrupt");
    return value;
  }
}

export function createSelectionCommandRepository() {
  return new LocalFileSelectionCommandRepository();
}

function assertEligibleSelection(
  universe: UniverseSnapshotArtifact,
  command: { groupId: string | null; venueInstrumentId: string; venueInstrumentVersionId: number }
) {
  const instrument = universe.items.find((item) => item.venueInstrumentId === command.venueInstrumentId);
  if (!instrument?.active || instrument.groupId !== command.groupId ||
      instrument.venueInstrumentVersionId !== command.venueInstrumentVersionId) {
    throw new SelectionError(409, "selection_instrument_changed");
  }
  if (selectionUnavailableReason(instrument)) {
    throw new SelectionError(409, "selection_instrument_ineligible");
  }
}

function validTime(value: string, nowMs: number) {
  const time = Date.parse(value);
  return Number.isFinite(time) && time <= nowMs;
}

function isSelectionCommand(payload: unknown): payload is SelectionCommand {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const value = payload as Partial<SelectionCommand>;
  return value.schemaVersion === 1 &&
    (typeof value.groupId === "string" || value.groupId === null) &&
    (value.groupId !== null || (Number.isSafeInteger(value.venueInstrumentVersionId) &&
      Number(value.venueInstrumentVersionId) > 0)) &&
    typeof value.venueInstrumentId === "string" &&
    typeof value.requestedAt === "string" && typeof value.heartbeatAt === "string" &&
    Number.isFinite(Date.parse(value.requestedAt)) &&
    Number.isFinite(Date.parse(value.heartbeatAt));
}
