import { realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";

export type MexcBudgetLane = "funding" | "foreground" | "recovery";
const LIMITS = { funding: 4, foreground: 2, recovery: 2 };
const WINDOW_MS = 2_000;
const APPLICATION_ID = 1_296_390_211;

export class MexcBudgetUnavailable extends Error {
  constructor() { super("MEXC shared budget unavailable"); }
}

// Injection keeps Node Vitest independent of Bun's native SQLite runtime.
export interface MexcBudgetStore {
  reserve(lane: MexcBudgetLane, now: number): number;
  cooldown(now: number, milliseconds: number): void;
}

export interface MexcBudget {
  acquire(lane: MexcBudgetLane, signal: AbortSignal, timeoutMs?: number): Promise<void>;
  cooldown(seconds?: number): Promise<void>;
}

interface SQLiteDatabase {
  exec(sql: string): void;
  query(sql: string): {
    get(...parameters: (string | number)[]): Record<string, number> | null;
    all(...parameters: (string | number)[]): Record<string, string | number>[];
    run(...parameters: (string | number)[]): unknown;
  };
  close(): void;
}
type SQLiteConstructor = new (path: string, options: { create: boolean }) => SQLiteDatabase;

export async function openMexcBudgetStore(path: string | undefined): Promise<MexcBudgetStore> {
  try {
    validateBudgetPath(path);
    // Deferred import: only a real MEXC HTTP acquisition requires Bun.
    const specifier = "bun:sqlite";
    const { Database } = await import(/* @vite-ignore */ specifier) as { Database: SQLiteConstructor };
    return new SQLiteMexcBudgetStore(path!, Database);
  } catch { throw new MexcBudgetUnavailable(); }
}

function validateBudgetPath(path: string | undefined): asserts path is string {
  if (!path || !isAbsolute(path) || resolve(path) !== path ||
    realpathSync(dirname(path)) !== dirname(path) || !statSync(dirname(path)).isDirectory()) {
    throw new MexcBudgetUnavailable();
  }
  try {
    if (realpathSync(path) !== path || !statSync(path).isFile()) throw new MexcBudgetUnavailable();
  } catch (cause) {
    if ((cause as NodeJS.ErrnoException).code !== "ENOENT") throw cause;
  }
}

class SQLiteMexcBudgetStore implements MexcBudgetStore {
  constructor(private path: string, private Database: SQLiteConstructor) {}

  private transaction<T>(now: number, run: (db: SQLiteDatabase, cooldownUntil: number) => T): T {
    validateBudgetPath(this.path);
    const db = new this.Database(this.path, { create: true });
    let active = false;
    try {
      db.exec("PRAGMA busy_timeout=25");
      db.exec("BEGIN IMMEDIATE");
      active = true;
      const applicationId = Number(db.query("PRAGMA application_id").get()?.application_id);
      if (applicationId === 0) {
        if (db.query("SELECT name FROM sqlite_master WHERE type='table'").all().length) {
          throw new MexcBudgetUnavailable();
        }
        db.exec(`PRAGMA application_id=${APPLICATION_ID}`);
        db.exec("CREATE TABLE mexc_budget_meta (id INTEGER PRIMARY KEY CHECK(id=1), " +
          "version INTEGER NOT NULL, cooldown_until_ms INTEGER NOT NULL, last_clock_ms INTEGER NOT NULL)");
        db.exec("INSERT INTO mexc_budget_meta VALUES (1,1,0,0)");
        db.exec("CREATE TABLE mexc_budget_attempts (at_ms INTEGER NOT NULL, " +
          "lane TEXT NOT NULL CHECK(lane IN ('funding','foreground','recovery')))");
        db.exec("CREATE INDEX mexc_budget_attempt_time ON mexc_budget_attempts(at_ms)");
      } else if (applicationId !== APPLICATION_ID) throw new MexcBudgetUnavailable();
      const meta = db.query("SELECT version,cooldown_until_ms,last_clock_ms FROM mexc_budget_meta WHERE id=1").get();
      if (!meta || meta.version !== 1 || !Number.isSafeInteger(meta.last_clock_ms) ||
          !Number.isSafeInteger(meta.cooldown_until_ms) || now < meta.last_clock_ms) throw new MexcBudgetUnavailable();
      db.query("UPDATE mexc_budget_meta SET last_clock_ms=? WHERE id=1").run(now);
      const result = run(db, meta.cooldown_until_ms);
      db.exec("COMMIT");
      active = false;
      return result;
    } finally {
      try { if (active) db.exec("ROLLBACK"); } finally { db.close(); }
    }
  }

  reserve(lane: MexcBudgetLane, now: number): number {
    return this.transaction(now, (db, cooldownUntil) => {
      db.query("DELETE FROM mexc_budget_attempts WHERE at_ms<=?").run(now - WINDOW_MS);
      const rows = db.query("SELECT at_ms,lane FROM mexc_budget_attempts ORDER BY at_ms").all();
      const waits = [cooldownUntil - now];
      if (rows.length >= 8) waits.push(Number(rows[rows.length - 8].at_ms) + WINDOW_MS - now);
      const laneRows = rows.filter(row => row.lane === lane);
      if (laneRows.length >= LIMITS[lane]) {
        waits.push(Number(laneRows[laneRows.length - LIMITS[lane]].at_ms) + WINDOW_MS - now);
      }
      const delay = Math.max(0, ...waits);
      if (delay === 0) db.query("INSERT INTO mexc_budget_attempts(at_ms,lane) VALUES (?,?)").run(now, lane);
      return delay;
    });
  }

  cooldown(now: number, milliseconds: number): void {
    this.transaction(now, (db) => {
      db.query("UPDATE mexc_budget_meta SET cooldown_until_ms=max(cooldown_until_ms,?) WHERE id=1")
        .run(now + milliseconds);
    });
  }
}

interface Options {
  store?: MexcBudgetStore;
  loadStore?: () => Promise<MexcBudgetStore>;
  now?: () => number;
  monotonicNow?: () => number;
  wait?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

export class SharedMexcBudget implements MexcBudget {
  private store?: MexcBudgetStore;
  private loadStore: () => Promise<MexcBudgetStore>;
  private now: () => number;
  private monotonicNow: () => number;
  private wait: (milliseconds: number, signal: AbortSignal) => Promise<void>;

  constructor(options: Options = {}) {
    this.store = options.store;
    this.loadStore = options.loadStore ?? (() => openMexcBudgetStore(process.env.PREP_WATCHDECK_MEXC_BUDGET_DB));
    this.now = options.now ?? Date.now;
    this.monotonicNow = options.monotonicNow ?? (() => performance.now());
    this.wait = options.wait ?? waitForBudget;
  }

  private async storage() {
    this.store ??= await this.loadStore();
    return this.store;
  }

  async acquire(lane: MexcBudgetLane, signal: AbortSignal, timeoutMs = 20_000): Promise<void> {
    if (!(lane in LIMITS) || !Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new MexcBudgetUnavailable();
    const deadline = this.monotonicNow() + timeoutMs;
    while (this.monotonicNow() < deadline) {
      signal.throwIfAborted();
      let delay: number;
      try {
        delay = (await this.storage()).reserve(lane, this.now());
        signal.throwIfAborted();
        if (delay === 0 && this.monotonicNow() < deadline) return;
      } catch (cause) {
        signal.throwIfAborted();
        delay = 50;
      }
      const remaining = deadline - this.monotonicNow();
      if (remaining > 0) await this.wait(Math.min(remaining, Math.max(1, delay), 250), signal);
    }
    throw new MexcBudgetUnavailable();
  }

  async cooldown(seconds = 2): Promise<void> {
    const milliseconds = Math.ceil(Math.max(2, Number.isFinite(seconds) ? seconds : 2) * 1_000);
    const deadline = this.monotonicNow() + 2_000;
    const signal = AbortSignal.timeout(2_000);
    while (this.monotonicNow() < deadline) {
      try { (await this.storage()).cooldown(this.now(), milliseconds); return; }
      catch {
        await this.wait(Math.min(50, Math.max(0, deadline - this.monotonicNow())), signal);
      }
    }
    throw new MexcBudgetUnavailable();
  }
}

function waitForBudget(milliseconds: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, milliseconds);
    function abort() { clearTimeout(timer); reject(signal.reason); }
    signal.addEventListener("abort", abort, { once: true });
  });
}

export const mexcBudget = new SharedMexcBudget();
