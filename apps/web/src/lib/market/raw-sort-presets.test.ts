import { describe, expect, it } from "vitest";
import {
  fifteenMinuteVolumeRatioState,
  rawSortLensForState,
  rawSortStateForLens,
  rawSortStateForTimeframe
} from "./raw-sort-presets";

describe("raw sort presets", () => {
  it("maps quick lenses without owning a timeframe", () => {
    expect(rawSortStateForLens("up")).toEqual({
      sortKey: "changePct",
      direction: "desc"
    });
    expect(rawSortStateForLens("down")).toEqual({
      sortKey: "changePct",
      direction: "asc"
    });
    expect(rawSortStateForLens("turnover")).toEqual({
      sortKey: "turnoverUsdt",
      direction: "desc"
    });
  });

  it("keeps ordinary and advanced sort state when switching timeframe", () => {
    expect(rawSortStateForTimeframe(rawSortStateForLens("down"))).toEqual(rawSortStateForLens("down"));
    expect(rawSortStateForTimeframe(rawSortStateForLens("turnover"))).toEqual(
      rawSortStateForLens("turnover")
    );
    expect(
      rawSortStateForTimeframe({
        sortKey: "attentionScore",
        direction: "desc"
      })
    ).toEqual({
      sortKey: "attentionScore",
      direction: "desc"
    });
  });

  it("leaves the fixed 15 minute volume ratio lens as upward change when switching timeframe", () => {
    expect(rawSortStateForTimeframe(fifteenMinuteVolumeRatioState)).toEqual(
      rawSortStateForLens("up")
    );
  });

  it("treats the volume ratio shortcut as explicitly 15m only", () => {
    expect(fifteenMinuteVolumeRatioState).toEqual({
      sortKey: "volumeRatio",
      direction: "desc"
    });
    expect(rawSortLensForState(fifteenMinuteVolumeRatioState)).toBe(null);
  });
});
