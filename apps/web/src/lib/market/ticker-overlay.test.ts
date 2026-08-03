import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.useRealTimers();
});

describe("TickerOverlay", () => {
  it("replaces full state, applies only contiguous deltas, and preserves untouched identity", async () => {
    const { TickerOverlay } = await import("./ticker-overlay.svelte");
    const overlay = new TickerOverlay();

    expect(
      overlay.applyBatch({
        schemaVersion: 1,
        sequence: 10,
        asOf: 1_000,
        full: true,
        updates: [
          ["BTCUSDT", 101, 1_000],
          ["ETHUSDT", 51, 1_000]
        ]
      })
    ).toBe("applied");
    const untouchedEth = overlay.tickers.get("ETHUSDT");
    const btcPrice = overlay.priceFor("BTCUSDT", 98, 97);
    const ethPrice = overlay.priceFor("ETHUSDT", 48, 47);

    expect(
      overlay.applyBatch({
        schemaVersion: 1,
        sequence: 11,
        asOf: 2_000,
        full: false,
        updates: [["BTCUSDT", 102, 2_000]]
      })
    ).toBe("applied");
    expect(overlay.tickers.get("BTCUSDT")?.lastPrice).toBe(102);
    expect(overlay.tickers.get("ETHUSDT")).toBe(untouchedEth);
    expect(overlay.priceFor("BTCUSDT", 98, 97)).not.toBe(btcPrice);
    expect(overlay.priceFor("ETHUSDT", 48, 47)).toBe(ethPrice);

    expect(
      overlay.applyBatch({
        schemaVersion: 1,
        sequence: 13,
        asOf: 3_000,
        full: false,
        updates: [["BTCUSDT", 999, 3_000]]
      })
    ).toBe("gap");
    expect(overlay.sequence).toBe(11);
    expect(overlay.tickers.get("BTCUSDT")?.lastPrice).toBe(102);

    expect(
      overlay.applyBatch({
        schemaVersion: 1,
        sequence: 14,
        asOf: 4_000,
        full: true,
        updates: [["SOLUSDT", 20, 4_000]]
      })
    ).toBe("applied");
    expect([...overlay.tickers.keys()]).toEqual(["SOLUSDT"]);
  });

  it("marks only boundary-crossing values stale and keeps the last numeric value visible", async () => {
    const { TickerOverlay } = await import("./ticker-overlay.svelte");
    const overlay = new TickerOverlay();
    overlay.applyBatch({
      schemaVersion: 1,
      sequence: 1,
      asOf: 4_000,
      full: true,
      updates: [
        ["BTCUSDT", 101, 1_000],
        ["ETHUSDT", 51, 4_000]
      ]
    });
    const freshEth = overlay.tickers.get("ETHUSDT");

    expect(overlay.refreshStaleness(7_000)).toEqual(["BTCUSDT"]);
    expect(overlay.tickers.get("BTCUSDT")?.stale).toBe(true);
    expect(overlay.tickers.get("ETHUSDT")).toBe(freshEth);
    expect(overlay.priceFor("BTCUSDT", 98, 97)).toEqual({
      value: 101,
      source: "hot",
      stale: true
    });
  });

  it("falls back from absent hot state to snapshot, analysis, then missing", async () => {
    const { TickerOverlay } = await import("./ticker-overlay.svelte");
    const overlay = new TickerOverlay();

    expect(overlay.priceFor("BTCUSDT", 98, 97)).toEqual({
      value: 98,
      source: "snapshot",
      stale: false
    });
    expect(overlay.priceFor("BTCUSDT", null, 97)).toEqual({
      value: 97,
      source: "analysis",
      stale: false
    });
    expect(overlay.priceFor("BTCUSDT", null, null)).toEqual({
      value: null,
      source: "missing",
      stale: false
    });
  });
});

describe("TickerPollController", () => {
  it("uses 1s, 2s, 4s and a 10s maximum retry backoff", async () => {
    const { tickerRetryDelayMs } = await import("./ticker-overlay.svelte");

    expect([1, 2, 3, 4, 5, 20].map(tickerRetryDelayMs)).toEqual([
      1_000,
      2_000,
      4_000,
      8_000,
      10_000,
      10_000
    ]);
  });

  it("stops applying a sequence gap and immediately recovers with full state", async () => {
    vi.useFakeTimers();
    const { TickerOverlay, TickerPollController } = await import("./ticker-overlay.svelte");
    const overlay = new TickerOverlay();
    const visibility = new FakeVisibilityDocument("visible");
    const fetchBatch = vi
      .fn()
      .mockResolvedValueOnce({
        schemaVersion: 1,
        sequence: 2,
        asOf: 2_000,
        full: true,
        updates: [["BTCUSDT", 102, 2_000]]
      })
      .mockResolvedValueOnce({
        schemaVersion: 1,
        sequence: 4,
        asOf: 4_000,
        full: false,
        updates: [["BTCUSDT", 999, 4_000]]
      })
      .mockResolvedValueOnce({
        schemaVersion: 1,
        sequence: 4,
        asOf: 4_000,
        full: true,
        updates: [["BTCUSDT", 104, 4_000]]
      });
    const controller = new TickerPollController({ overlay, fetchBatch, visibility });

    controller.start();
    await flushPromises();
    expect(overlay.sequence).toBe(2);

    vi.advanceTimersByTime(1_000);
    await flushPromises();
    expect(fetchBatch.mock.calls.map(([after]) => after)).toEqual([0, 2, 0]);
    expect(overlay.sequence).toBe(4);
    expect(overlay.tickers.get("BTCUSDT")?.lastPrice).toBe(104);
    controller.stop();
  });

  it("pauses while hidden, requests a full state immediately on visibility, and never overlaps", async () => {
    vi.useFakeTimers();
    const { TickerOverlay, TickerPollController } = await import("./ticker-overlay.svelte");
    const overlay = new TickerOverlay();
    const visibility = new FakeVisibilityDocument("hidden");
    let resolveFetch: ((value: undefined) => void) | undefined;
    const fetchBatch = vi.fn(
      () =>
        new Promise<undefined>((resolve) => {
          resolveFetch = resolve;
        })
    );
    const controller = new TickerPollController({ overlay, fetchBatch, visibility });

    controller.start();
    expect(fetchBatch).not.toHaveBeenCalled();

    visibility.setState("visible");
    await Promise.resolve();
    expect(fetchBatch).toHaveBeenCalledTimes(1);
    expect(fetchBatch).toHaveBeenLastCalledWith(0);

    visibility.setState("hidden");
    visibility.setState("visible");
    vi.advanceTimersByTime(10_000);
    await Promise.resolve();
    expect(fetchBatch).toHaveBeenCalledTimes(1);

    resolveFetch?.(undefined);
    await Promise.resolve();
    visibility.setState("hidden");
    vi.advanceTimersByTime(10_000);
    await Promise.resolve();
    expect(fetchBatch).toHaveBeenCalledTimes(1);

    visibility.setState("visible");
    await Promise.resolve();
    expect(fetchBatch).toHaveBeenCalledTimes(2);
    expect(fetchBatch).toHaveBeenLastCalledWith(0);
    controller.stop();
  });
});

class FakeVisibilityDocument extends EventTarget {
  constructor(public visibilityState: DocumentVisibilityState) {
    super();
  }

  setState(state: DocumentVisibilityState) {
    this.visibilityState = state;
    this.dispatchEvent(new Event("visibilitychange"));
  }
}

async function flushPromises() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}
