import { describe, expect, test } from "vitest";
import {
  calculatePriceChange,
  dailyBaselineAt,
  formatPriceChange,
  isReferenceTime,
  readStoredReferenceTime,
  writeStoredReferenceTime
} from "./price-change";

describe("daily price change reference", () => {
  test.each([
    ["2026-09-10T14:59:59.999Z", "00:00", "2026-09-09T15:00:00.000Z"],
    ["2026-09-10T15:00:00.000Z", "00:00", "2026-09-10T15:00:00.000Z"],
    ["2026-09-11T04:00:00.000Z", "09:00", "2026-09-11T00:00:00.000Z"],
    ["2026-09-11T00:06:59.999Z", "09:07", "2026-09-10T00:07:00.000Z"],
    ["2026-09-11T00:07:00.000Z", "09:07", "2026-09-11T00:07:00.000Z"],
    ["2027-01-01T00:00:00+09:00", "00:00", "2026-12-31T15:00:00.000Z"],
    ["2028-03-01T00:00:00+09:00", "23:59", "2028-02-29T14:59:00.000Z"]
  ])("resolves %s at JST %s without the host timezone", (now, reference, expected) => {
    expect(new Date(dailyBaselineAt(Date.parse(now), reference)).toISOString()).toBe(expected);
  });

  test("accepts minute precision and rejects ambiguous or invalid settings", () => {
    for (const time of ["00:00", "09:07", "23:59"]) expect(isReferenceTime(time)).toBe(true);
    for (const time of ["0:00", "24:00", "12:60", "09:00:00", " 09:00", null, 9]) {
      expect(isReferenceTime(time)).toBe(false);
    }
    expect(() => dailyBaselineAt(NaN, "00:00")).toThrow(RangeError);
    expect(() => dailyBaselineAt(Date.now(), "24:00")).toThrow(RangeError);
  });

  test("uses the same positive price basis and never formats an invalid change as zero", () => {
    expect(calculatePriceChange(103, 100)).toBeCloseTo(3);
    expect(calculatePriceChange(97, 100)).toBeCloseTo(-3);
    expect(calculatePriceChange(100, 100)).toBe(0);
    for (const prices of [[0, 100], [100, 0], [-1, 1], [Infinity, 1], [1, NaN], [1e308, 1e-308]]) {
      expect(calculatePriceChange(prices[0], prices[1])).toBeNull();
    }
    expect(formatPriceChange(3)).toBe("+3.00%");
    expect(formatPriceChange(-3)).toBe("-3.00%");
    expect(formatPriceChange(-0.001)).toBe("0.00%");
  });

  test("preserves a valid setting and recovers from corrupt or unavailable storage", () => {
    expect(readStoredReferenceTime({ getItem: () => "09:07" })).toBe("09:07");
    expect(readStoredReferenceTime({ getItem: () => "24:00" })).toBe("00:00");
    expect(readStoredReferenceTime({ getItem: () => { throw new Error("denied"); } })).toBe("00:00");
    let saved = "";
    const storage = { setItem: (_key: string, value: string) => { saved = value; } };
    expect(writeStoredReferenceTime(storage, "09:07")).toBe(true);
    expect(saved).toBe("09:07");
    expect(writeStoredReferenceTime(storage, "24:00")).toBe(false);
    expect(saved).toBe("09:07");
    expect(writeStoredReferenceTime({ setItem: () => { throw new Error("full"); } }, "00:00")).toBe(false);
  });
});
