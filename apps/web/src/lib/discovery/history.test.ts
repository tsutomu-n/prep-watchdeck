import { expect, test } from "vitest";
import { discoveryFixture } from "./discovery-test-fixture";
import { mergeDiscoveryEpisodes } from "./history";

// Actual paging sequence: read latest100..51, next50..1, then poll latest110..61.
test("polling retains the middle of read history and replaces updated episode states by ID", () => {
  const episode = discoveryFixture().episodes[0];
  const range = (from: number, to: number) => Array.from({ length: from - to + 1 }, (_, offset) => ({
    ...episode, id: String(from - offset), firstObservedAt: from - offset,
    state: "ended" as const, endedAt: from - offset, endReason: "condition_cleared"
  }));
  const latest = range(100, 51);
  const read = mergeDiscoveryEpisodes(range(50, 1), latest);
  const refresh = range(110, 61);
  refresh.find(item => item.id === "70")!.endReason = "identity_changed";
  const merged = mergeDiscoveryEpisodes(refresh, read);
  expect(merged.map(item => Number(item.id))).toEqual(Array.from({ length: 110 }, (_, index) => 110 - index));
  expect(merged.find(item => item.id === "70")!.endReason).toBe("identity_changed");
  expect(mergeDiscoveryEpisodes(refresh, merged)).toEqual(merged);
});
