import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";
import { nativeActivityFixture } from "$lib/market/native-activity-test-fixture";
import { readNativeActivity } from "./native-activity-repository";

test("native activity rejects duplicate identities, false ready values and broken windows", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-activity-"));
  const path = join(root, "native-activity.json");
  try {
    const payload = nativeActivityFixture(Date.parse("2026-10-08T06:00:00Z"));
    await writeFile(path, JSON.stringify(payload));
    expect((await readNativeActivity(path)).rows[0].windows["15m"].relativeRatio.value).toBe(3);
    for (const corrupt of [
      (data: typeof payload) => { data.rows.push(data.rows[0]); },
      (data: typeof payload) => { data.rows[0].windows["15m"].relativeRatio.value = null; },
      (data: typeof payload) => { data.rows[0].windows["15m"].history[0].endAt = data.candleCutoff; },
      (data: typeof payload) => { data.rows[0].windows["15m"].baselineDays = 1; }
    ]) {
      const invalid = structuredClone(payload);
      corrupt(invalid);
      await writeFile(path, JSON.stringify(invalid));
      await expect(readNativeActivity(path)).rejects.toThrow("native activity invalid");
    }
  } finally { await rm(root, { recursive: true, force: true }); }
});
