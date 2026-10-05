import { expect, test } from "vitest";
import { defaultPreferences, normalizePreferences, parsePreferences, readPreferences } from "./workspace-preferences";
import { displayNumber } from "../market/number-display";
import { formatPrice } from "../market/universe-view";

test("malformed stored settings fall back per field and reject unsafe thresholds", () => {
  expect(parsePreferences("{broken")).toEqual(defaultPreferences);
  expect(normalizePreferences({ layout: "ultra", surgeRatio: 0, directionPct: NaN,
    quantityDecimals: 30, initialPage: "https://outside.test", referenceViewId: "../unsafe" }))
    .toEqual({ ...defaultPreferences, layout: "ultra" });
  const value = normalizePreferences({ surgeRatio: 2.5, directionPct: 0.5, percentDecimals: 4, referenceViewId: "my_view-1" });
  expect(value.surgeRatio).toBe(2.5);
  expect(value.directionPct).toBe(0.5);
  expect(value.percentDecimals).toBe(4);
  expect(value.referenceViewId).toBe("my_view-1");
});

test("rounded non-price values preserve missing, zero and signed tiny amounts", () => {
  expect(displayNumber(null, 2)).toBe("—");
  expect(displayNumber(Infinity, 2)).toBe("—");
  expect(displayNumber(0, 2)).toBe("0");
  expect(displayNumber(0.00001, 2)).toBe("<0.01");
  expect(displayNumber(-0.00001, 2)).toBe(">−0.01");
  expect(displayNumber(1234.56789, 3)).toBe("1,234.568");
  expect(displayNumber(1234567.89, 2, true)).toBe("1.23M");
  expect(formatPrice(0.000123456789)).toBe("0.000123456789");
});


test("legacy density becomes normal without losing other settings; v2 ultra survives", () => {
  for (const layout of ["standard", "ultra"]) {
    expect(readPreferences(null, JSON.stringify({ layout, percentDecimals: 4, chartVolume: false })))
      .toEqual({ ...defaultPreferences, layout: "normal", percentDecimals: 4, chartVolume: false });
  }
  expect(readPreferences(JSON.stringify({ layout: "ultra" }), JSON.stringify({ layout: "standard" })).layout).toBe("ultra");
  expect(readPreferences("{broken", JSON.stringify({ layout: "ultra" }))).toEqual(defaultPreferences);
});
