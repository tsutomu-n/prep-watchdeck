import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { DecisionHistory, DecisionInput, ManualDecision } from "$lib/market/decisions";
import { isFavoriteTarget } from "./user-workspace-repository";
import { resolveMarketStatePaths } from "./market-state-paths";
import { withLockFile } from "./lock-file-guard";
import { writeJsonFileAtomic } from "./atomic-json-store";

export const DECISION_MAX_BYTES = 16 * 1024 * 1024;
export class DecisionError extends Error {
  constructor(public readonly status: number, public readonly code: string) { super(code); }
}
export function isDecisionInput(value: unknown): value is DecisionInput {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const item = value as DecisionInput;
  return Object.keys(item).every(key => ["id", "action", "reason", "target", "episodeId", "snapshot"].includes(key)) &&
    typeof item.id === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(item.id) &&
    ["watch", "skip"].includes(item.action) && typeof item.reason === "string" &&
    item.reason.trim().length > 0 && item.reason.length <= 2000 && isFavoriteTarget(item.target) &&
    typeof item.episodeId === "string" && item.episodeId.length > 0 && item.episodeId.length <= 160 &&
    !!item.snapshot && typeof item.snapshot === "object" && !Array.isArray(item.snapshot) &&
    Buffer.byteLength(JSON.stringify(item.snapshot)) <= 131_072;
}

export class LocalFileDecisionRepository {
  constructor(private readonly path = resolve(resolveMarketStatePaths().stateDir, "manual-decisions.json"),
    private readonly now = () => new Date()) {}
  async read() { return await withLockFile(`${this.path}.lock`, () => this.readUnlocked()); }
  async save(input: DecisionInput, expectedRevision: number): Promise<DecisionHistory> {
    if (!isDecisionInput(input) || !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
      throw new DecisionError(400, "decision_invalid");
    }
    return await withLockFile(`${this.path}.lock`, async () => {
      const current = await this.readUnlocked();
      const duplicate = current.decisions.find(entry => entry.id === input.id);
      if (duplicate) {
        const { recordedAt: _, ...saved } = duplicate;
        if (JSON.stringify(saved) !== JSON.stringify(input)) throw new DecisionError(409, "decision_id_conflict");
        return current;
      }
      if (current.revision !== expectedRevision) throw new DecisionError(409, "decision_conflict");
      const next: DecisionHistory = { ...current, revision: current.revision + 1,
        decisions: [...current.decisions, { ...input, recordedAt: this.now().toISOString() }] };
      if (next.decisions.length > 1000 || Buffer.byteLength(`${JSON.stringify(next, null, 2)}\n`) > DECISION_MAX_BYTES) {
        throw new DecisionError(413, "decision_limit");
      }
      await writeJsonFileAtomic(this.path, next);
      return next;
    });
  }
  private async readUnlocked(): Promise<DecisionHistory> {
    let bytes: Buffer;
    try { bytes = await readFile(this.path); }
    catch (cause) {
      if ((cause as NodeJS.ErrnoException).code === "ENOENT") return { schemaVersion: 1, revision: 0, decisions: [] };
      throw new DecisionError(500, "decision_unavailable");
    }
    if (bytes.byteLength > DECISION_MAX_BYTES) throw new DecisionError(500, "decision_invalid");
    let value: DecisionHistory;
    try { value = JSON.parse(bytes.toString("utf-8")); } catch { throw new DecisionError(500, "decision_invalid"); }
    if (!value || value.schemaVersion !== 1 || !Number.isSafeInteger(value.revision) || value.revision < 0 ||
        !Array.isArray(value.decisions) || value.decisions.length > 1000 ||
        Object.keys(value).some(key => !["schemaVersion", "revision", "decisions"].includes(key)) ||
        new Set(value.decisions.map(entry => entry.id)).size !== value.decisions.length ||
        value.decisions.some((entry: ManualDecision) => {
          const { recordedAt, ...input } = entry;
          return !isDecisionInput(input) || typeof recordedAt !== "string" || !Number.isFinite(Date.parse(recordedAt));
        })) throw new DecisionError(500, "decision_invalid");
    return value;
  }
}
