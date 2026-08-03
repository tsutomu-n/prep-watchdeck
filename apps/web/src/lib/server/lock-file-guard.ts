import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rm, stat } from "node:fs/promises";
import { dirname } from "node:path";

export class LockFileTimeoutError extends Error {
  constructor(lockPath: string) {
    super(`Timed out waiting for lock: ${lockPath}`);
    this.name = "LockFileTimeoutError";
  }
}

export type LockFileGuardOptions = {
  timeoutMs?: number;
  retryDelayMs?: number;
  staleMs?: number;
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
};

const DEFAULT_TIMEOUT_MS = 5000;
const DEFAULT_RETRY_DELAY_MS = 25;
const DEFAULT_STALE_MS = 30_000;

export async function withLockFile<T>(
  lockPath: string,
  task: () => Promise<T>,
  options: LockFileGuardOptions = {}
): Promise<T> {
  const release = await acquireLockFile(lockPath, options);
  try {
    return await task();
  } finally {
    await release();
  }
}

export async function acquireLockFile(lockPath: string, options: LockFileGuardOptions = {}) {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const retryDelayMs = options.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
  const staleMs = options.staleMs ?? DEFAULT_STALE_MS;
  const now = options.now ?? Date.now;
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const startedAt = now();

  await mkdir(dirname(lockPath), { recursive: true });

  while (true) {
    try {
      const token = randomUUID();
      const handle = await open(lockPath, "wx");
      try {
        await handle.writeFile(lockPayload(now(), token), "utf-8");
      } finally {
        await handle.close();
      }
      return async () => releaseLockFile(lockPath, token);
    } catch (cause) {
      if (!isAlreadyExistsError(cause)) throw cause;
      if (await removeIfStale(lockPath, staleMs, now)) {
        continue;
      }
      if (now() - startedAt >= timeoutMs) {
        throw new LockFileTimeoutError(lockPath);
      }
      await sleep(retryDelayMs);
    }
  }
}

async function releaseLockFile(lockPath: string, token: string) {
  let content: string;
  try {
    content = await readFile(lockPath, "utf-8");
  } catch (cause) {
    if (isNotFoundError(cause)) return;
    throw cause;
  }

  if (lockToken(content) !== token) return;
  await rm(lockPath, { force: true });
}

async function removeIfStale(lockPath: string, staleMs: number, now: () => number) {
  try {
    const info = await stat(lockPath);
    if (now() - info.mtimeMs < staleMs) return false;
    await readFile(lockPath, "utf-8").catch(() => "");
    await rm(lockPath, { force: true });
    return true;
  } catch (cause) {
    if (isNotFoundError(cause)) return true;
    throw cause;
  }
}

function lockPayload(nowMs: number, token: string) {
  return JSON.stringify({ pid: process.pid, token, createdAt: new Date(nowMs).toISOString() }) + "\n";
}

function lockToken(content: string) {
  try {
    const payload: unknown = JSON.parse(content);
    if (
      typeof payload === "object" &&
      payload !== null &&
      "token" in payload &&
      typeof payload.token === "string"
    ) {
      return payload.token;
    }
  } catch {
    return null;
  }
  return null;
}

function isAlreadyExistsError(cause: unknown) {
  return typeof cause === "object" && cause !== null && "code" in cause && cause.code === "EEXIST";
}

function isNotFoundError(cause: unknown) {
  return typeof cause === "object" && cause !== null && "code" in cause && cause.code === "ENOENT";
}
