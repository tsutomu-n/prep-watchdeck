import { randomUUID } from "node:crypto";
import { mkdir, open, readdir, rename, rm, stat } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";

export type AtomicWriteOptions = {
  now?: () => number;
  staleTmpMs?: number;
  beforeRename?: (tmpPath: string) => void | Promise<void>;
};

const DEFAULT_STALE_TMP_MS = 24 * 60 * 60 * 1000;

export async function writeJsonFileAtomic(
  path: string,
  payload: unknown,
  options: AtomicWriteOptions = {}
) {
  await writeTextFileAtomic(path, `${JSON.stringify(payload, null, 2)}\n`, options);
}

export async function writeTextFileAtomic(
  path: string,
  content: string,
  options: AtomicWriteOptions = {}
) {
  const targetPath = resolve(path);
  const dir = dirname(targetPath);
  await mkdir(dir, { recursive: true });
  await cleanupStaleAtomicTemps(targetPath, {
    staleTmpMs: options.staleTmpMs ?? DEFAULT_STALE_TMP_MS,
    now: options.now
  });

  const tmpPath = atomicTempPath(targetPath, options.now?.() ?? Date.now());
  let handle: Awaited<ReturnType<typeof open>> | null = null;

  try {
    handle = await open(tmpPath, "wx");
    await handle.writeFile(content, "utf-8");
    await handle.sync();
    await handle.close();
    handle = null;
    await options.beforeRename?.(tmpPath);
    await rename(tmpPath, targetPath);
    await fsyncDirectory(dir);
  } catch (cause) {
    if (handle) {
      await handle.close().catch(() => undefined);
    }
    await rm(tmpPath, { force: true }).catch(() => undefined);
    throw cause;
  }
}

export async function cleanupStaleAtomicTemps(
  path: string,
  {
    staleTmpMs = DEFAULT_STALE_TMP_MS,
    now = Date.now
  }: {
    staleTmpMs?: number;
    now?: () => number;
  } = {}
) {
  const targetPath = resolve(path);
  const dir = dirname(targetPath);
  const prefix = `.${basename(targetPath)}.`;
  const cutoff = now() - staleTmpMs;

  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return;
  }

  await Promise.all(
    entries
      .filter((entry) => entry.startsWith(prefix) && entry.endsWith(".tmp"))
      .map(async (entry) => {
        const tmpPath = resolve(dir, entry);
        try {
          const info = await stat(tmpPath);
          if (info.mtimeMs <= cutoff) {
            await rm(tmpPath, { force: true });
          }
        } catch {
          // A concurrent writer may already have removed the temp file.
        }
      })
  );
}

function atomicTempPath(path: string, nowMs: number) {
  return resolve(dirname(path), `.${basename(path)}.${process.pid}.${nowMs}.${randomUUID()}.tmp`);
}

async function fsyncDirectory(dir: string) {
  let handle: Awaited<ReturnType<typeof open>> | null = null;
  try {
    handle = await open(dir, "r");
    await handle.sync();
  } catch {
    // Directory fsync is best-effort across platforms.
  } finally {
    await handle?.close().catch(() => undefined);
  }
}
