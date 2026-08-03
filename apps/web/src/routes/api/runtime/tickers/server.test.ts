import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const originalRuntimePath = process.env.SCANNER_TICKER_RUNTIME_PATH;

afterEach(() => {
  if (originalRuntimePath === undefined) {
    delete process.env.SCANNER_TICKER_RUNTIME_PATH;
  } else {
    process.env.SCANNER_TICKER_RUNTIME_PATH = originalRuntimePath;
  }
});

describe("ticker runtime API", () => {
  it("returns 204 when no newer batch exists or the runtime file is absent", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-route-"));
    process.env.SCANNER_TICKER_RUNTIME_PATH = join(root, "ticker-runtime.json");
    try {
      const { GET } = await import("./+server");
      const missing = await GET(event(0));
      expect(missing.status).toBe(204);
      expect(missing.headers.get("cache-control")).toBe("no-store");

      await writeFile(process.env.SCANNER_TICKER_RUNTIME_PATH, JSON.stringify(validRuntime()), "utf-8");
      const unchanged = await GET(event(2));
      expect(unchanged.status).toBe(204);
      expect(unchanged.headers.get("cache-control")).toBe("no-store");
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("returns delta only for the immediately previous sequence and full otherwise", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-route-"));
    process.env.SCANNER_TICKER_RUNTIME_PATH = join(root, "ticker-runtime.json");
    try {
      await writeFile(process.env.SCANNER_TICKER_RUNTIME_PATH, JSON.stringify(validRuntime()), "utf-8");
      const { GET } = await import("./+server");

      const delta = await GET(event(1));
      expect(delta.status).toBe(200);
      expect(delta.headers.get("cache-control")).toBe("no-store");
      await expect(delta.json()).resolves.toMatchObject({ full: false, sequence: 2 });

      const full = await GET(event(0));
      expect(full.status).toBe(200);
      expect(full.headers.get("cache-control")).toBe("no-store");
      await expect(full.json()).resolves.toMatchObject({
        full: true,
        sequence: 2,
        updates: [
          ["BTCUSDT", 102, 200],
          ["ETHUSDT", 51, 200]
        ]
      });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("returns 503 for invalid runtime payloads", async () => {
    const root = await mkdtemp(join(tmpdir(), "prep-watchdeck-ticker-route-"));
    process.env.SCANNER_TICKER_RUNTIME_PATH = join(root, "ticker-runtime.json");
    try {
      await writeFile(process.env.SCANNER_TICKER_RUNTIME_PATH, "{partial", "utf-8");
      const { GET } = await import("./+server");

      await expect(GET(event(0))).rejects.toMatchObject({ status: 503 });
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects negative, fractional, and unsafe integer sequence inputs", async () => {
    const { GET } = await import("./+server");

    await expect(GET(rawEvent("-1"))).rejects.toMatchObject({ status: 400 });
    await expect(GET(rawEvent("1.5"))).rejects.toMatchObject({ status: 400 });
    await expect(GET(rawEvent("9007199254740992"))).rejects.toMatchObject({ status: 400 });
  });
});

function event(after: number) {
  return { url: new URL(`http://localhost/api/runtime/tickers?after=${after}`) } as never;
}

function rawEvent(after: string) {
  return { url: new URL(`http://localhost/api/runtime/tickers?after=${after}`) } as never;
}

function validRuntime() {
  return {
    schemaVersion: 1,
    sequence: 2,
    asOf: 2_000,
    fullUpdates: [
      ["BTCUSDT", 102, 200],
      ["ETHUSDT", 51, 200]
    ],
    deltaUpdates: [["BTCUSDT", 102, 200]]
  };
}
