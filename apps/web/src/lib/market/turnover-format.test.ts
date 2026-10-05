import { describe, expect, test } from "vitest";
import { formatTurnover } from "./turnover-format";
import { formatPrice } from "./universe-view";

describe("売買代金の表示だけを丸める", () => {
  test.each([
    [108129798.20669937, 2, "108,129,798.21"],
    [108129798.20669937, 0, "108,129,798"],
    [108129798.20669937, 4, "108,129,798.2067"],
    [1250, 2, "1,250"], [0, 2, "0"],
    [0.0001, 2, "<0.01"], [0.01, 0, "<1"],
    [0.006, 2, "0.01"], [0.00000001, 4, "<0.0001"],
  ])("%s を小数 %s 桁で %s と表示", (value, digits, expected) => {
    expect(formatTurnover(value, digits)).toBe(expected);
  });
  test("略記も指定桁を使い、欠測と価格の精度を保つ", () => {
    expect(formatTurnover(108129798.20669937, 4, true)).toBe("108.1298M");
    expect(formatTurnover(null, 2)).toBe("—");
    expect(formatTurnover(Number.NaN, 2)).toBe("—");
    expect(formatTurnover(12.3456, 99)).toBe("12.35");
    expect(formatPrice(0.000123456789)).toBe("0.000123456789");
  });
});
