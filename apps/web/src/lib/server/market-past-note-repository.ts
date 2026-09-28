import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isMarketPastNote, type MarketPastNote, type MarketPastNoteContext } from "$lib/market-past-note/market-past-note";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { resolveMarketStatePaths } from "./market-state-paths";

const RETENTION_MS = 60 * 24 * 60 * 60 * 1000;
const SAFE_INSTRUMENT_ID = /^[a-z]+:[A-Za-z0-9_.-]+$/;

type NoteFile = {
  schemaVersion: 1 | 2;
  venueInstrumentId: string;
  notes: MarketPastNote[];
};

export class PastNoteError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}

export class LocalFileMarketPastNoteRepository {
  constructor(
    private readonly rootDir = resolveMarketStatePaths().pastNotesDir,
    private readonly now = () => new Date()
  ) {}

  async list(venueInstrumentId: string) {
    const path = this.pathFor(venueInstrumentId);
    return await withLockFile(`${path}.lock`, async () => {
      const { notes, revisionToken } = await this.read(path, venueInstrumentId);
      return { notes: this.active(notes), revisionToken };
    });
  }

  async save(
    venueInstrumentId: string, reason: string, note: string, expectedRevisionToken: string,
    context?: MarketPastNoteContext
  ) {
    const path = this.pathFor(venueInstrumentId);
    return await withLockFile(`${path}.lock`, async () => {
      const { notes: stored, revisionToken } = await this.read(path, venueInstrumentId);
      if (revisionToken !== expectedRevisionToken) throw new PastNoteError(409, "past_note_conflict");
      const current = this.active(stored);
      const observedAt = this.now();
      const next: MarketPastNote = {
        venueInstrumentId,
        reason: reason || "過去注記",
        note,
        observedAt: observedAt.toISOString(),
        expiresAt: new Date(observedAt.getTime() + RETENTION_MS).toISOString(),
        ...(context ? { context } : {})
      };
      const notes = [next, ...current.filter((item) => item.reason !== next.reason)];
      const payload: NoteFile = { schemaVersion: 2, venueInstrumentId, notes };
      await writeJsonFileAtomic(path, payload);
      const saved = await this.read(path, venueInstrumentId);
      return { notes, revisionToken: saved.revisionToken };
    });
  }

  private active(notes: MarketPastNote[]) {
    const nowMs = this.now().getTime();
    return notes.filter((note) => Date.parse(note.expiresAt) > nowMs);
  }

  private async read(path: string, venueInstrumentId: string) {
    let bytes: Buffer;
    try {
      bytes = await readFile(path);
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code === "ENOENT") {
        return { notes: [] as MarketPastNote[], revisionToken: "absent" };
      }
      throw new PastNoteError(500, "past_note_unavailable");
    }
    let payload: unknown;
    try {
      payload = JSON.parse(bytes.toString("utf-8"));
    } catch {
      throw new PastNoteError(500, "past_note_corrupt");
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new PastNoteError(500, "past_note_corrupt");
    }
    const file = payload as Partial<NoteFile>;
    if (![1, 2].includes(file.schemaVersion ?? 0) || file.venueInstrumentId !== venueInstrumentId ||
        !Array.isArray(file.notes) ||
        !file.notes.every((item) => isMarketPastNote(item) && item.venueInstrumentId === venueInstrumentId)) {
      throw new PastNoteError(500, "past_note_corrupt");
    }
    return {
      notes: file.notes,
      revisionToken: createHash("sha256").update(bytes).digest("hex")
    };
  }

  private pathFor(venueInstrumentId: string) {
    if (!SAFE_INSTRUMENT_ID.test(venueInstrumentId)) {
      throw new PastNoteError(400, "invalid_venue_instrument_id");
    }
    return resolve(this.rootDir, `${venueInstrumentId}.json`);
  }
}

export function createMarketPastNoteRepository() {
  return new LocalFileMarketPastNoteRepository();
}
