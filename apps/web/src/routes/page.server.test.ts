import { describe, expect, test } from "vitest";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("./+page.server.ts", import.meta.url), "utf8");

describe("monitoring-only dashboard server load", () => {
  test("loads only monitoring repositories and runtime context", () => {
    expect(source).toContain('from "$lib/server/snapshot-repository"');
    expect(source).toContain('from "$lib/server/past-note-repository"');
    expect(source).toContain('from "$lib/server/dashboard-view-settings-repository"');
    expect(source).toContain('from "$lib/server/service-state-repository"');
    expect(source).toContain('from "$lib/server/runtime-target"');

    expect(source).not.toMatch(/trade-memo-repository|TradeMemo/);
    expect(source).not.toMatch(/attack-ticket-repository|AttackTicket/);
    expect(source).not.toMatch(/weekly-review|WeeklyReview/);
  });

  test("returns only the monitoring dashboard payload", () => {
    const successPayload = source.match(
      /const snapshot = await createSnapshotRepository\(\)\.latest\(\);\s+return \{([\s\S]*?)\n\s+\};/
    )?.[1];

    expect(successPayload).toBeDefined();
    expect(successPayload).toContain("snapshot:");
    expect(successPayload).toContain("pastNotes:");
    expect(successPayload).toContain("dashboardViewSettings:");
    expect(successPayload).toContain("serviceState,");
    expect(successPayload).toContain("runtime:");
    expect(successPayload).not.toMatch(/tradeMemos|attackTickets|weeklyReview/);
  });
});
