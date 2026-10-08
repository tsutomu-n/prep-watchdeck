import { expect, test } from "vitest";
import { rankingFixture } from "./ranking-test-fixture";
import { nativeActivityFixture } from "./native-activity-test-fixture";
import { nativeActivity } from "./native-activity";

const now = Date.parse("2026-10-08T06:00:00Z");
const row = rankingFixture(undefined, now).rows.find(row => row.asset === "BTC")!;

test("activity belongs to exact Bitget version and expires independently of reference ranking", () => {
  const artifact = nativeActivityFixture(now);
  expect(nativeActivity(row, artifact, now).row?.windows["15m"].relativeRatio.value).toBe(3);
  expect(nativeActivity(row, artifact, now + 120_001).row).toBeNull();
  expect(nativeActivity(row, { ...artifact, candleCutoff: new Date(now - 300_001).toISOString() }, now).row).toBeNull();
  expect(nativeActivity(row, { ...artifact, generatedAt: new Date(now + 10_000).toISOString() }, now).row).toBeNull();
  expect(nativeActivity(row, { ...artifact, rows: [{ ...artifact.rows[0], venueInstrumentVersionId: 2 }] }, now).row).toBeNull();
  expect(nativeActivity(row, { ...artifact, rows: [artifact.rows[0], artifact.rows[0]] }, now).row).toBeNull();
  expect(nativeActivity({ ...row, originals: [{ ...row.originals[0], venue: "hyperliquid" }] }, artifact, now).row).toBeNull();
  expect(nativeActivity(row, null, now).reason).toBeTruthy();
});

test("missing baseline never hides valid current activity, zero or the observed decline", () => {
  const artifact = nativeActivityFixture(now);
  const window = artifact.rows[0].windows["15m"];
  window.relativeRatio = { status: "history_missing", value: null };
  window.current.turnover = { status: "ready", value: 0 };
  window.previousChangePct = { status: "ready", value: -100 };
  const result = nativeActivity(row, artifact, now).row!.windows["15m"];
  expect(result.relativeRatio.value).toBeNull();
  expect(result.current.turnover.value).toBe(0);
  expect(result.previousChangePct.value).toBe(-100);
});
