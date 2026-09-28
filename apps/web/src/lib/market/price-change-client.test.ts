import { describe, expect, test, vi } from "vitest";
import { PriceChangeClient, type PriceChangeState, type PriceChangeTarget } from "./price-change-client";
import { dailyBaselineAt, type DailyPriceChange } from "./price-change";

const target = (id: string, version = 1): PriceChangeTarget => ({
  venueInstrumentId: id,
  venueInstrumentVersionId: version
});

function fixture(now: number, id = "a", version = 1, referenceTime = "00:00"): DailyPriceChange {
  return {
    venueInstrumentId: id,
    venueInstrumentVersionId: version,
    referenceTime,
    baselineAt: new Date(dailyBaselineAt(now, referenceTime)).toISOString(),
    generatedAt: new Date(now).toISOString(),
    status: "ready",
    reason: null,
    baselinePrice: 100,
    currentPrice: 103,
    currentCandleAt: new Date(Math.floor(now / 60_000) * 60_000).toISOString(),
    changePercent: 3
  };
}

async function flush(): Promise<void> {
  for (let index = 0; index < 6; index += 1) await Promise.resolve();
}

function harness(initialNow = Date.parse("2026-09-11T04:00:00.000Z")) {
  let now = initialNow;
  const updates = new Map<string, PriceChangeState>();
  const calls: {
    url: URL;
    signal: AbortSignal;
    resolve: (response: Response) => void;
    reject: (error: Error) => void;
  }[] = [];
  // Deliberately ignore abort so cancellation must preserve actual concurrency accounting.
  const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((resolve, reject) => {
    calls.push({
      url: new URL(String(input), "http://localhost"),
      signal: init!.signal!,
      resolve,
      reject
    });
  }));
  const onUpdate = vi.fn((id: string, state: PriceChangeState) => updates.set(id, state));
  const client = new PriceChangeClient({ fetch: fetcher as typeof fetch, now: () => now, onUpdate });
  async function respond(index: number, body?: unknown, status = 200): Promise<void> {
    const call = calls[index];
    call.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body ?? fixture(
        now, call.url.searchParams.get("instrument")!, 1, call.url.searchParams.get("referenceTime")!
      )
    } as Response);
    await flush();
  }
  return {
    client, calls, updates, onUpdate, respond,
    now: () => now,
    setNow: (value: number) => { now = value; },
    advance: (value: number) => { now += value; }
  };
}

describe("PriceChangeClient scheduling", () => {
  test("deduplicates targets, preserves priority, and caps actual concurrent requests at two", async () => {
    const h = harness();
    h.client.setTargets([target("selected"), target("a"), target("selected"), target("b")]);
    expect(h.calls.map((call) => call.url.searchParams.get("instrument"))).toEqual(["selected", "a"]);
    expect(h.updates.get("b")?.status).toBe("queued");
    h.client.setTargets([target("selected"), target("a"), target("b")]);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    await h.respond(0);
    expect(h.calls.map((call) => call.url.searchParams.get("instrument"))).toEqual(["selected", "a", "b"]);
    await h.respond(1);
    await h.respond(2);
    expect([...h.updates.values()].map((state) => state.status)).toEqual(["ready", "ready", "ready"]);
    h.client.dispose();
  });

  test("drops queued offscreen targets and waits for ignored aborts before using their slots", async () => {
    const h = harness();
    h.client.setTargets([target("a"), target("b"), target("offscreen")]);
    h.client.setTargets([target("selected"), target("visible")]);
    expect(h.calls).toHaveLength(2);
    expect(h.calls.every((call) => call.signal.aborted)).toBe(true);
    expect(h.updates.get("offscreen")).toEqual({ status: "idle", data: null, message: null });
    await h.respond(0);
    expect(h.calls[2].url.searchParams.get("instrument")).toBe("selected");
    expect(h.updates.get("a")?.data).toBeNull();
    await h.respond(1);
    expect(h.calls[3].url.searchParams.get("instrument")).toBe("visible");
    expect(h.calls.some((call) => call.url.searchParams.get("instrument") === "offscreen")).toBe(false);
    h.client.dispose();
  });

  test("pause cancels pending work, resume respects occupied slots, and disposal ignores late results", async () => {
    const h = harness();
    h.client.setTargets([target("a"), target("b"), target("c")]);
    h.client.setPaused(true);
    expect(h.calls.every((call) => call.signal.aborted)).toBe(true);
    expect([...h.updates.values()].every((state) => state.data === null && state.status === "idle")).toBe(true);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    h.client.setPaused(false);
    expect(h.calls).toHaveLength(2);
    await h.respond(0);
    expect(h.calls).toHaveLength(3);
    expect(h.calls[2].url.searchParams.get("instrument")).toBe("a");
    expect(h.updates.get("a")?.status).toBe("loading");
    h.client.dispose();
    const updateCount = h.onUpdate.mock.calls.length;
    await h.respond(1);
    await h.respond(2);
    h.client.setTargets([target("d")]);
    h.client.refresh();
    expect(h.calls).toHaveLength(3);
    expect(h.onUpdate).toHaveBeenCalledTimes(updateCount);
  });

  test("reuses results across snapshot updates and revisits, but retries failures only after the TTL", async () => {
    const h = harness();
    h.client.setTargets([target("a")]);
    await h.respond(0);
    for (let index = 0; index < 5; index += 1) {
      h.advance(5_000);
      h.client.setTargets([target("a")]);
    }
    h.client.setTargets([]);
    h.client.setTargets([target("a")]);
    expect(h.calls).toHaveLength(1);
    expect(h.updates.get("a")?.status).toBe("ready");
    h.advance(35_000);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    expect(h.updates.get("a")?.data).toBeNull();
    await h.respond(1, { error: "price_change_provider_unavailable" }, 503);
    expect(h.updates.get("a")).toMatchObject({ status: "error", data: null });
    h.client.setTargets([]);
    h.client.setTargets([target("a")]);
    h.advance(59_999);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    expect(h.updates.get("a")).toMatchObject({ status: "error", data: null });
    h.advance(1);
    h.client.refresh();
    expect(h.calls).toHaveLength(3);
    await h.respond(2);
    expect(h.updates.get("a")?.status).toBe("ready");
    h.client.dispose();
  });

  test("instrument version changes invalidate cache and reject older in-flight versions", async () => {
    const h = harness();
    h.client.setTargets([target("a")]);
    await h.respond(0);
    h.client.setTargets([target("a", 2)]);
    expect(h.updates.get("a")).toMatchObject({ status: "loading", data: null });
    h.client.setTargets([target("a", 3)]);
    expect(h.calls[1].signal.aborted).toBe(true);
    await h.respond(1, fixture(h.now(), "a", 2));
    expect(h.updates.get("a")).toMatchObject({ status: "loading", data: null });
    await h.respond(2, fixture(h.now(), "a", 3));
    expect(h.updates.get("a")?.data?.venueInstrumentVersionId).toBe(3);
    h.client.dispose();
  });

  test("changing the reference clears cached values and ignores a previous setting's response", async () => {
    const h = harness();
    h.client.setTargets([target("a")]);
    const oldResponse = fixture(h.now());
    h.client.setReferenceTime("09:07");
    expect(h.calls[0].signal.aborted).toBe(true);
    expect(h.calls[1].url.searchParams.get("referenceTime")).toBe("09:07");
    await h.respond(0, oldResponse);
    expect(h.updates.get("a")).toMatchObject({ status: "loading", data: null });
    await h.respond(1);
    expect(h.updates.get("a")?.data?.referenceTime).toBe("09:07");
    h.client.setReferenceTime("09:07");
    expect(h.calls).toHaveLength(2);
    expect(() => h.client.setReferenceTime("24:00")).toThrow(RangeError);
    h.client.dispose();
  });

  test("midnight refresh invalidates a request even inside the 60-second TTL", async () => {
    const h = harness(Date.parse("2026-09-11T14:59:59.000Z"));
    h.client.setTargets([target("a")]);
    const yesterday = fixture(h.now());
    h.advance(2_000);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    expect(h.calls[0].signal.aborted).toBe(true);
    await h.respond(0, yesterday);
    expect(h.updates.get("a")).toMatchObject({ status: "loading", data: null });
    await h.respond(1);
    expect(h.updates.get("a")?.data?.baselineAt).toBe("2026-09-11T15:00:00.000Z");
    h.client.dispose();
  });

  test("a response crossing midnight detects the new anchor without waiting for the next timer", async () => {
    const h = harness(Date.parse("2026-09-11T14:59:59.000Z"));
    h.client.setTargets([target("a")]);
    const yesterday = fixture(h.now());
    h.advance(2_000);
    await h.respond(0, yesterday);
    expect(h.calls).toHaveLength(2);
    expect(h.updates.get("a")).toMatchObject({ status: "loading", data: null });
    await h.respond(1);
    expect(h.updates.get("a")?.data?.baselineAt).toBe("2026-09-11T15:00:00.000Z");
    h.client.dispose();
  });

  test("paused refresh clears yesterday's numeric data and resumes with the current anchor", async () => {
    const h = harness(Date.parse("2026-09-11T14:59:59.000Z"));
    h.client.setTargets([target("a")]);
    await h.respond(0);
    h.client.setPaused(true);
    h.advance(2_000);
    h.client.refresh();
    expect(h.updates.get("a")).toEqual({ status: "idle", data: null, message: null });
    expect(h.calls).toHaveLength(1);
    h.client.setPaused(false);
    expect(h.calls).toHaveLength(2);
    await h.respond(1);
    expect(h.updates.get("a")?.data?.baselineAt).toBe("2026-09-11T15:00:00.000Z");
    h.client.dispose();
  });

  test("paused and cached data lose their numeric value when the candle or result expires", async () => {
    const h = harness();
    h.client.setTargets([target("a")]);
    await h.respond(0);
    h.client.setPaused(true);
    h.advance(120_001);
    h.client.refresh();
    expect(h.updates.get("a")).toMatchObject({ status: "stale", data: null });
    expect(h.calls).toHaveLength(1);
    h.client.setPaused(false);
    expect(h.calls).toHaveLength(2);
    await h.respond(1);
    expect(h.updates.get("a")?.status).toBe("ready");
    h.client.dispose();
  });

  test("the offscreen result cache evicts the oldest result after 256 instruments", async () => {
    const h = harness();
    for (let index = 0; index < 257; index += 1) {
      h.client.setTargets([target(String(index))]);
      await h.respond(index);
    }
    h.client.setTargets([target("256")]);
    h.client.setTargets([target("255")]);
    expect(h.calls).toHaveLength(257);
    expect(h.updates.get("255")?.status).toBe("ready");
    h.client.setTargets([target("0")]);
    expect(h.calls).toHaveLength(258);
    expect(h.updates.get("0")).toMatchObject({ status: "loading", data: null });
    h.client.dispose();
  });
});

describe("PriceChangeClient response validation", () => {
  test("at the daily boundary accepts a measured baseline close as zero, but rejects older candles or generation", async () => {
    const now = Date.parse("2026-09-11T15:00:01.000Z");
    const anchor = dailyBaselineAt(now, "00:00");
    for (const [candleAt, generatedAt, expectedStatus] of [
      [anchor - 60_000, now, "ready"],
      [anchor - 120_000, now, "error"],
      [anchor - 60_000, anchor - 1, "error"]
    ] as const) {
      const h = harness(now);
      h.client.setTargets([target("a")]);
      await h.respond(0, {
        ...fixture(now),
        currentPrice: 100,
        changePercent: 0,
        currentCandleAt: new Date(candleAt).toISOString(),
        generatedAt: new Date(generatedAt).toISOString()
      });
      expect(h.updates.get("a")?.status).toBe(expectedStatus);
      expect(h.updates.get("a")?.data?.changePercent ?? null).toBe(expectedStatus === "ready" ? 0 : null);
      h.client.dispose();
    }
  });

  test.each([
    ["identity", { venueInstrumentId: "other" }],
    ["version", { venueInstrumentVersionId: 2 }],
    ["reference time", { referenceTime: "09:00" }],
    ["day anchor", { baselineAt: "2026-09-09T15:00:00.000Z" }],
    ["missing generation", { generatedAt: undefined }],
    ["future generation", { generatedAt: "2026-09-11T04:00:01.000Z" }],
    ["zero baseline", { baselinePrice: 0 }],
    ["negative current", { currentPrice: -1 }],
    ["infinite price", { currentPrice: Infinity }],
    ["missing price", { currentPrice: null }],
    ["nonfinite change", { changePercent: NaN }],
    ["incorrect math", { changePercent: 30 }],
    ["missing candle", { currentCandleAt: null }],
    ["future candle", { currentCandleAt: "2026-09-11T04:01:00.000Z" }],
    ["ready with a missing reason", { reason: "baseline_missing" }],
    ["unknown availability", { status: "unavailable", reason: "unknown", changePercent: null }],
    ["unavailable with numeric change", { status: "unavailable", reason: "baseline_missing", baselinePrice: null }],
    ["false baseline missing", { status: "unavailable", reason: "baseline_missing", changePercent: null }],
    ["false latest missing", { status: "unavailable", reason: "latest_missing", changePercent: null }]
  ])("rejects %s instead of displaying an untrusted number", async (_name, patch) => {
    const h = harness();
    h.client.setTargets([target("a")]);
    await h.respond(0, { ...fixture(h.now()), ...patch });
    expect(h.updates.get("a")).toMatchObject({ status: "error", data: null });
    h.client.refresh();
    expect(h.calls).toHaveLength(1);
    h.client.dispose();
  });

  test.each(["baseline_missing", "latest_missing", "latest_stale"] as const)(
    "accepts %s only as unavailable and clears the previous success",
    async (reason) => {
      const h = harness();
      h.client.setTargets([target("a")]);
      await h.respond(0);
      h.advance(60_000);
      h.client.refresh();
      const body = fixture(h.now());
      body.status = "unavailable";
      body.reason = reason;
      body.changePercent = null;
      if (reason === "baseline_missing") body.baselinePrice = null;
      if (reason === "latest_missing") { body.currentPrice = null; body.currentCandleAt = null; }
      if (reason === "latest_stale") body.currentCandleAt = new Date(h.now() - 180_000).toISOString();
      await h.respond(1, body);
      expect(h.updates.get("a")).toMatchObject({ status: "unavailable", data: { changePercent: null, reason } });
      expect(h.updates.get("a")?.message).toBeTruthy();
      h.client.dispose();
    }
  );

  test.each(["result", "candle"])("expired %s does not become ready and uses bounded retries", async (kind) => {
    const h = harness();
    h.client.setTargets([target("a")]);
    const body = fixture(h.now() - 121_000);
    if (kind === "candle") body.generatedAt = new Date(h.now()).toISOString();
    await h.respond(0, body);
    expect(h.updates.get("a")).toMatchObject({ status: "stale", data: null });
    h.advance(59_999);
    h.client.refresh();
    expect(h.calls).toHaveLength(1);
    h.advance(1);
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    h.client.dispose();
  });

  test("network and malformed JSON failures clear numeric data without immediate retries", async () => {
    const h = harness();
    h.client.setTargets([target("a")]);
    await h.respond(0);
    h.advance(60_000);
    h.client.refresh();
    h.calls[1].reject(new TypeError("Failed to fetch"));
    await flush();
    expect(h.updates.get("a")).toMatchObject({ status: "error", data: null });
    h.client.refresh();
    expect(h.calls).toHaveLength(2);
    h.advance(60_000);
    h.client.refresh();
    h.calls[2].resolve({ ok: true, status: 200, json: async () => { throw new SyntaxError("invalid JSON"); } } as unknown as Response);
    await flush();
    expect(h.updates.get("a")).toMatchObject({ status: "error", data: null });
    expect(h.calls).toHaveLength(3);
    h.client.dispose();
  });
});
