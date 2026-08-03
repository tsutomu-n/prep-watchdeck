import { describe, expect, it } from "vitest";

describe("shouldAutoRefreshDashboard", () => {
  it("allows visible service snapshots only while service is ok or backfilling", async () => {
    const { shouldAutoRefreshDashboard } = await import("./dashboard-refresh.svelte");
    const serviceSnapshot = { summary: { serviceSource: "duckdb-service" } };

    expect(
      shouldAutoRefreshDashboard(serviceSnapshot, { view: { status: "ok" } }, "visible")
    ).toBe(true);
    expect(
      shouldAutoRefreshDashboard(
        serviceSnapshot,
        { view: { status: "backfilling" } },
        "visible"
      )
    ).toBe(true);
    expect(
      shouldAutoRefreshDashboard(serviceSnapshot, { view: { status: "stale" } }, "visible")
    ).toBe(false);
    expect(
      shouldAutoRefreshDashboard(serviceSnapshot, { view: { status: "error" } }, "visible")
    ).toBe(false);
  });

  it("does not use a leftover service state to refresh live or hidden snapshots", async () => {
    const { shouldAutoRefreshDashboard } = await import("./dashboard-refresh.svelte");
    const healthyService = { view: { status: "ok" } };

    expect(
      shouldAutoRefreshDashboard(
        { summary: { serviceSource: "live-scan" } },
        healthyService,
        "visible"
      )
    ).toBe(false);
    expect(
      shouldAutoRefreshDashboard(
        { summary: { serviceSource: "duckdb-service" } },
        healthyService,
        "hidden"
      )
    ).toBe(false);
    expect(
      shouldAutoRefreshDashboard(
        { summary: { serviceSource: "duckdb-service" } },
        undefined,
        "visible"
      )
    ).toBe(false);
  });
});
