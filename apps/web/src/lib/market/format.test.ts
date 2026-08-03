import { describe, expect, it } from "vitest";
import { formatCompactNumber, formatDateTime, formatNumber, formatRatio, formatUsd } from "./format";

describe("market format helpers", () => {
  it("formats known numeric values for the Japanese UI", () => {
    expect(formatNumber(1234.567, "%")).toBe("1,234.57%");
    expect(formatCompactNumber(1234.567)).toBe("1,234.57");
    expect(formatUsd(56.6)).toBe("$56.6");
    expect(formatRatio(1.25)).toBe("1.25");
  });

  it("keeps existing missing-value labels", () => {
    expect(formatNumber(null)).toBe("未取得");
    expect(formatCompactNumber(undefined)).toBe("-");
    expect(formatUsd(Number.NaN)).toBe("未取得");
    expect(formatRatio("1.2")).toBe("未取得");
  });

  it("formats timestamps through the local Japanese locale", () => {
    expect(formatDateTime("2026-06-23T12:34:56Z")).toMatch(/2026/);
  });
});
