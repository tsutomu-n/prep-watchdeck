import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { expect, test, vi } from "vitest";
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

test.each([false, true])("initial HTML and hydrated density agree with mobile=%s", (mobile) => {
  const script = readFileSync(new URL("../../app.html", import.meta.url), "utf8").match(/<script>([\s\S]*?)<\/script>/)![1];
  const matchMedia = () => ({ matches: mobile });
  const fallback = mobile ? "ultra" : "normal";
  vi.stubGlobal("window", { matchMedia });
  try {
    for (const [current, legacy, expected] of [
      [null, null, fallback],
      ["{broken", null, fallback],
      ['{"layout":"invalid"}', null, fallback],
      ['{"layout":"normal"}', null, "normal"],
      ['{"layout":"ultra"}', null, "ultra"],
      [null, '{"layout":"ultra","percentDecimals":4}', fallback]
    ]) {
      const attributes: Record<string, string> = {};
      runInNewContext(script, {
        matchMedia,
        localStorage: { getItem: (key: string) => key.endsWith(":v2") ? current : key.endsWith(":v1") ? legacy : null },
        document: { documentElement: { setAttribute: (key: string, value: string) => { attributes[key] = value; } } }
      });
      expect(attributes["data-layout"]).toBe(expected);
      expect(readPreferences(current, legacy).layout).toBe(expected);
    }
  } finally {
    vi.unstubAllGlobals();
  }
});
