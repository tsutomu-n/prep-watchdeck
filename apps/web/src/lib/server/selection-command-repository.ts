import { readFile } from "node:fs/promises";
import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { createMarketArtifactRepository, type MarketArtifactRepository } from "./market-artifact-repository";
import { resolveMarketStatePaths } from "./market-state-paths";

export type SelectionCommand = {
  schemaVersion: 1;
  groupId: string;
  venueInstrumentId: string;
  requestedAt: string;
  heartbeatAt: string;
};

export class LocalFileSelectionCommandRepository {
  constructor(
    private readonly path = resolveMarketStatePaths().selectionCommandPath,
    private readonly artifacts: MarketArtifactRepository = createMarketArtifactRepository(),
    private readonly now = () => new Date()
  ) {}

  async write(groupId: string, venueInstrumentId: string): Promise<SelectionCommand> {
    const normalizedGroupId = groupId.trim();
    const normalizedInstrumentId = venueInstrumentId.trim();
    if (!normalizedGroupId || !normalizedInstrumentId) {
      throw new Error("groupId and venueInstrumentId are required");
    }

    const { universe } = await this.artifacts.latest();
    assertEligibleSelection(universe, normalizedGroupId, normalizedInstrumentId);

    return await withLockFile(`${this.path}.lock`, async () => {
      const now = this.now().toISOString();
      const previous = await this.readCurrent();
      const sameIdentity =
        previous?.groupId === normalizedGroupId &&
        previous.venueInstrumentId === normalizedInstrumentId;
      const command: SelectionCommand = {
        schemaVersion: 1,
        groupId: normalizedGroupId,
        venueInstrumentId: normalizedInstrumentId,
        requestedAt: sameIdentity ? previous.requestedAt : now,
        heartbeatAt: now
      };
      await writeJsonFileAtomic(this.path, command);
      return command;
    });
  }

  private async readCurrent(): Promise<SelectionCommand | null> {
    try {
      const payload: unknown = JSON.parse(await readFile(this.path, "utf-8"));
      return isSelectionCommand(payload) ? payload : null;
    } catch {
      return null;
    }
  }
}

export function createSelectionCommandRepository() {
  return new LocalFileSelectionCommandRepository();
}

function assertEligibleSelection(
  universe: UniverseSnapshotArtifact,
  groupId: string,
  venueInstrumentId: string
) {
  const instrument = universe.items.find((item) => item.venueInstrumentId === venueInstrumentId);
  if (!instrument || !instrument.active || instrument.groupId !== groupId) {
    throw new Error("selection is not an active grouped instrument in the current universe");
  }
}

function isSelectionCommand(payload: unknown): payload is SelectionCommand {
  if (!payload || typeof payload !== "object") return false;
  const value = payload as Partial<SelectionCommand>;
  return (
    value.schemaVersion === 1 &&
    typeof value.groupId === "string" &&
    typeof value.venueInstrumentId === "string" &&
    typeof value.requestedAt === "string" &&
    typeof value.heartbeatAt === "string"
  );
}
