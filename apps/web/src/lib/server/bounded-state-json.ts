import { constants } from "node:fs";
import { lstat, open } from "node:fs/promises";
import { dirname, resolve } from "node:path";

export class StateFileError extends Error {
  constructor(public readonly kind: "missing" | "unavailable") {
    super(kind);
  }
}

/** Read a fixed local state file without following a final symlink or unbounded growth. */
export async function readBoundedStateJson(path: string, maximum: number): Promise<unknown> {
  try {
    let parentPath = dirname(resolve(path));
    while (true) {
      const parent = await lstat(parentPath);
      if (!parent.isDirectory() || parent.isSymbolicLink()) throw new StateFileError("unavailable");
      const next = dirname(parentPath);
      if (next === parentPath) break;
      parentPath = next;
    }
    const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const info = await handle.stat();
      if (!info.isFile() || info.size > maximum) throw new StateFileError("unavailable");
      const chunks: Buffer[] = [];
      const buffer = Buffer.allocUnsafe(65_536);
      let total = 0;
      while (true) {
        const { bytesRead } = await handle.read(buffer, 0, buffer.length, null);
        if (bytesRead === 0) break;
        total += bytesRead;
        if (total > maximum) throw new StateFileError("unavailable");
        chunks.push(Buffer.from(buffer.subarray(0, bytesRead)));
      }
      return JSON.parse(Buffer.concat(chunks).toString("utf8")) as unknown;
    } finally {
      await handle.close();
    }
  } catch (cause) {
    if (cause instanceof StateFileError) throw cause;
    if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
      throw new StateFileError("missing");
    }
    throw new StateFileError("unavailable");
  }
}
