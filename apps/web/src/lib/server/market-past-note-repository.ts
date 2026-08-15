import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isMarketPastNote, type MarketPastNote } from "$lib/market-past-note/market-past-note";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { resolveMarketStatePaths } from "./market-state-paths";

const RETENTION_MS = 60 * 24 * 60 * 60 * 1000;
const SAFE_INSTRUMENT_ID = /^[a-z]+:[A-Za-z0-9_.-]+$/;

type NoteFile = {
  schemaVersion: 1;
  venueInstrumentId: string;
  notes: MarketPastNote[];
};

export class LocalFileMarketPastNoteRepository {
  constructor(
    private readonly rootDir = resolveMarketStatePaths().pastNotesDir,
    private readonly now = () => new Date()
  ) {}

  async list(venueInstrumentId: string): Promise<MarketPastNote[]> {
    const path = this.pathFor(venueInstrumentId);
    return await withLockFile(`${path}.lock`, async () => {
      const notes = await this.read(path, venueInstrumentId);
      const active = this.active(notes);
      if (active.length !== notes.length) await this.write(path, venueInstrumentId, active);
      return active;
    });
  }

  async save(venueInstrumentId: string, reason: string, note: string): Promise<MarketPastNote[]> {
    const path = this.pathFor(venueInstrumentId);
    return await withLockFile(`${path}.lock`, async () => {
      const current = this.active(await this.read(path, venueInstrumentId));
      const observedAt = this.now();
      const next: MarketPastNote = {
        venueInstrumentId,
        reason: reason || "過去注記",
        note,
        observedAt: observedAt.toISOString(),
        expiresAt: new Date(observedAt.getTime() + RETENTION_MS).toISOString()
      };
      const notes = [
        next,
        ...current.filter((item) => item.reason !== next.reason)
      ];
      await this.write(path, venueInstrumentId, notes);
      return notes;
    });
  }

  private active(notes: MarketPastNote[]) {
    const nowMs = this.now().getTime();
    return notes.filter((note) => Date.parse(note.expiresAt) > nowMs);
  }

  private async read(path: string, venueInstrumentId: string): Promise<MarketPastNote[]> {
    try {
      const payload: unknown = JSON.parse(await readFile(path, "utf-8"));
      if (!payload || typeof payload !== "object") return [];
      const file = payload as Partial<NoteFile>;
      if (
        file.schemaVersion !== 1 ||
        file.venueInstrumentId !== venueInstrumentId ||
        !Array.isArray(file.notes)
      ) {
        return [];
      }
      return file.notes.filter(
        (note) => isMarketPastNote(note) && note.venueInstrumentId === venueInstrumentId
      );
    } catch {
      return [];
    }
  }

  private async write(path: string, venueInstrumentId: string, notes: MarketPastNote[]) {
    const payload: NoteFile = { schemaVersion: 1, venueInstrumentId, notes };
    await writeJsonFileAtomic(path, payload);
  }

  private pathFor(venueInstrumentId: string) {
    if (!SAFE_INSTRUMENT_ID.test(venueInstrumentId)) {
      throw new Error("invalid venueInstrumentId");
    }
    return resolve(this.rootDir, `${venueInstrumentId}.json`);
  }
}

export function createMarketPastNoteRepository() {
  return new LocalFileMarketPastNoteRepository();
}
