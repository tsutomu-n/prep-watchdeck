import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isPastNote, type PastNote } from "$lib/past-note/past-note";
import { writeJsonFileAtomic } from "./atomic-json-store";
import { withLockFile } from "./lock-file-guard";
import { resolveStatePaths } from "./state-paths";

type PastNoteFile = {
  notes: PastNote[];
};

const TWO_MONTHS_MS = 60 * 24 * 60 * 60 * 1000;

export class LocalFilePastNoteRepository {
  constructor(
    private readonly rootDir = defaultPastNotesDir(),
    private readonly now = () => new Date()
  ) {}

  async list() {
    return await withLockFile(this.lockPath(), async () => this.listUnlocked());
  }

  async save(note: PastNote) {
    return await withLockFile(this.lockPath(), async () => {
      const current = await this.listUnlocked();
      const next = [
        note,
        ...current.filter((item) => !(item.symbol === note.symbol && item.reason === note.reason))
      ];
      const { active, archived } = this.rotate(next);
      await this.writeCurrent(active);
      await this.appendArchives(archived);
      return active;
    });
  }

  private async listUnlocked() {
    const file = await this.readCurrent();
    const { active, archived } = this.rotate(file.notes);
    if (archived.length > 0 || active.length !== file.notes.length) {
      await this.writeCurrent(active);
      await this.appendArchives(archived);
    }
    return active;
  }

  private rotate(notes: PastNote[]) {
    const cutoffMs = this.now().getTime() - TWO_MONTHS_MS;
    const active: PastNote[] = [];
    const archived: PastNote[] = [];

    for (const note of notes.filter(isPastNote)) {
      const observedAtMs = Date.parse(note.observedAt);
      const expiresAtMs = Date.parse(note.expiresAt);
      if (observedAtMs <= cutoffMs || expiresAtMs <= this.now().getTime()) {
        archived.push(note);
      } else {
        active.push(note);
      }
    }

    return { active, archived };
  }

  private async readCurrent(): Promise<PastNoteFile> {
    try {
      const payload: unknown = JSON.parse(await readFile(this.currentPath(), "utf-8"));
      if (!payload || typeof payload !== "object" || !Array.isArray((payload as PastNoteFile).notes)) {
        return { notes: [] };
      }
      return { notes: (payload as PastNoteFile).notes.filter(isPastNote) };
    } catch {
      return { notes: [] };
    }
  }

  private async writeCurrent(notes: PastNote[]) {
    await writeJsonFileAtomic(this.currentPath(), { notes });
  }

  private async appendArchives(notes: PastNote[]) {
    for (const note of notes) {
      const archivePath = this.archivePath(note);
      await withLockFile(`${archivePath}.lock`, async () => {
        const archive = await this.readArchive(archivePath);
        const deduped = archive.notes.filter(
          (item) => !(item.symbol === note.symbol && item.observedAt === note.observedAt)
        );
        await writeJsonFileAtomic(archivePath, { notes: [note, ...deduped] });
      });
    }
  }

  private async readArchive(path: string): Promise<PastNoteFile> {
    try {
      const payload: unknown = JSON.parse(await readFile(path, "utf-8"));
      if (!payload || typeof payload !== "object" || !Array.isArray((payload as PastNoteFile).notes)) {
        return { notes: [] };
      }
      return { notes: (payload as PastNoteFile).notes.filter(isPastNote) };
    } catch {
      return { notes: [] };
    }
  }

  private currentPath() {
    return resolve(this.rootDir, "current.json");
  }

  private lockPath() {
    return resolve(this.rootDir, "current.json.lock");
  }

  private archivePath(note: PastNote) {
    const observedAt = new Date(note.observedAt);
    const month = Number.isNaN(observedAt.getTime())
      ? "unknown"
      : `${observedAt.getUTCFullYear()}-${String(observedAt.getUTCMonth() + 1).padStart(2, "0")}`;
    return resolve(this.rootDir, "archive", month, `past-notes-${month}.json`);
  }
}

export function createPastNoteRepository() {
  return new LocalFilePastNoteRepository();
}

export function createPastNote(symbol: string, reason: string, note: string, now = new Date()): PastNote {
  const observedAt = now.toISOString();
  const expiresAt = new Date(now.getTime() + TWO_MONTHS_MS).toISOString();
  return {
    symbol,
    reason: reason || "過去注記",
    observedAt,
    expiresAt,
    note
  };
}

function defaultPastNotesDir() {
  return resolveStatePaths().pastNotesDir;
}
