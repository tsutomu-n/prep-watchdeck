import { describe, expect, it } from "vitest";
import {
  formatCompactNumber,
  formatDateTime,
  formatMarketPrice,
  formatNumber,
  formatRatio,
  formatUsd
} from "./format";

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

  it("keeps enough precision for market prices below one", () => {
    expect(formatMarketPrice(55_290.8123)).toBe("55,290.81");
    expect(formatMarketPrice(1.23456)).toBe("1.235");
    expect(formatMarketPrice(0.123456)).toBe("0.1235");
    expect(formatMarketPrice(0.0123456)).toBe("0.01235");
    expect(formatMarketPrice(0.00123456)).toBe("0.001235");
    expect(formatMarketPrice(0.0000123456)).toBe("0.00001235");
  });

  it("does not present missing or non-positive market prices as zero", () => {
    expect(formatMarketPrice(undefined)).toBe("-");
    expect(formatMarketPrice(Number.NaN)).toBe("-");
    expect(formatMarketPrice(0)).toBe("-");
    expect(formatMarketPrice(-1)).toBe("-");
  });

  it("formats timestamps through the local Japanese locale", () => {
    expect(formatDateTime("2026-06-23T12:34:56Z")).toMatch(/2026/);
  });
});
