import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const originalSnapshotPath = process.env.SCANNER_SNAPSHOT_PATH;

afterEach(() => {
  if (originalSnapshotPath === undefined) {
    delete process.env.SCANNER_SNAPSHOT_PATH;
  } else {
    process.env.SCANNER_SNAPSHOT_PATH = originalSnapshotPath;
  }
});

describe("dashboard snapshot API", () => {
  it("returns 204 when afterRunId is already current", async () => {
    const fixture = await fixtureSnapshot();
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-snapshot-"));
    process.env.SCANNER_SNAPSHOT_PATH = join(root, "latest.json");
    try {
      await writeFile(process.env.SCANNER_SNAPSHOT_PATH, JSON.stringify(fixture), "utf-8");
      const { GET } = await import("./+server");

      const response = await GET(event(`?afterRunId=${fixture.runId}`));

      expect(response.status).toBe(204);
      expect(await response.text()).toBe("");
      expect(response.headers.get("cache-control")).toBe("no-store");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("returns the already-thin snapshot without changing its structure", async () => {
    const fixture = await fixtureSnapshot();
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-snapshot-"));
    process.env.SCANNER_SNAPSHOT_PATH = join(root, "latest.json");
    try {
      await writeFile(process.env.SCANNER_SNAPSHOT_PATH, JSON.stringify(fixture), "utf-8");
      const { GET } = await import("./+server");

      const response = await GET(event("?afterRunId=older-run"));

      expect(response.status).toBe(200);
      expect(await response.json()).toEqual(fixture);
      expect(response.headers.get("cache-control")).toBe("no-store");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("returns 503 when the snapshot cannot be parsed or validated", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-dashboard-snapshot-"));
    process.env.SCANNER_SNAPSHOT_PATH = join(root, "latest.json");
    try {
      await writeFile(process.env.SCANNER_SNAPSHOT_PATH, "{partial", "utf-8");
      const { GET } = await import("./+server");

      await expect(GET(event("?afterRunId=run-1"))).rejects.toMatchObject({ status: 503 });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

function event(search: string) {
  return { url: new URL(`http://localhost/api/dashboard/snapshot${search}`) } as never;
}

async function fixtureSnapshot() {
  return JSON.parse(await readFile("../../fixtures/snapshots/basic.json", "utf-8")) as {
    runId: string;
    [key: string]: unknown;
  };
}
