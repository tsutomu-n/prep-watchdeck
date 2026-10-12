import { describe, expect, test } from "vitest";
import { MexcBudgetUnavailable, SharedMexcBudget } from "./mexc-budget";

describe("MEXC shared admission transport", () => {
  test("storage failure expires without granting an HTTP permit", async () => {
    let now = 0;
    let attempts = 0;
    const budget = new SharedMexcBudget({
      loadStore: async () => { attempts++; throw new Error("unavailable"); },
      monotonicNow: () => now,
      wait: async (delay, signal) => { signal.throwIfAborted(); now += delay; }
    });
    await expect(budget.acquire("foreground", new AbortController().signal, 100))
      .rejects.toBeInstanceOf(MexcBudgetUnavailable);
    expect(attempts).toBe(2);
    expect(now).toBe(100);
  });

  test("cancellation during a shared cooldown does not reserve again", async () => {
    const controller = new AbortController();
    let reservations = 0;
    const budget = new SharedMexcBudget({
      store: { reserve: () => { reservations++; return 2_000; }, cooldown: () => {} },
      wait: async () => { controller.abort(); controller.signal.throwIfAborted(); }
    });
    await expect(budget.acquire("foreground", controller.signal)).rejects.toThrow();
    expect(reservations).toBe(1);
  });
});
