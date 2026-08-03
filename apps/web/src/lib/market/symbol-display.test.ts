import { describe, expect, it } from "vitest";
import { formatDisplaySymbol } from "./symbol-display";

describe("symbol display", () => {
  it("removes common quote suffixes for visible labels", () => {
    expect(formatDisplaySymbol("BTCUSDT")).toBe("BTC");
    expect(formatDisplaySymbol("10000NEXUSDT")).toBe("10000NEX");
    expect(formatDisplaySymbol("ALTUSDC")).toBe("ALT");
    expect(formatDisplaySymbol("FOOUSDGO")).toBe("FOO");
  });

  it("keeps symbols without a known quote suffix", () => {
    expect(formatDisplaySymbol("ethbtc")).toBe("ETHBTC");
    expect(formatDisplaySymbol("USDT")).toBe("USDT");
  });
});
