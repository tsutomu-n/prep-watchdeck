import { describe, expect, it } from "vitest";
import {
  applyChartFontFamily,
  applyChartThemePalette,
  readChartFontFamily,
  readChartThemePalette
} from "./chart-theme";

function tokenSource(values: Record<string, string>): Pick<CSSStyleDeclaration, "getPropertyValue"> {
  return {
    getPropertyValue(name: string) {
      return values[name] ?? "";
    }
  };
}

const values = {
  "--chart-surface": " #151813 ",
  "--chart-text": " #cbd3c0 ",
  "--chart-grid": " #252b22 ",
  "--chart-border": " #394034 ",
  "--chart-up": " #9beaa7 ",
  "--chart-down": " #ff9a8d ",
  "--chart-focus": " #d8ff38 ",
  "--chart-volume-up": " rgba(155, 234, 167, 0.45) ",
  "--chart-volume-down": " rgba(255, 154, 141, 0.45) "
};
const supportedColors = new Set(Object.values(values).map((value) => value.trim()));
const supportsColor = (value: string) => supportedColors.has(value);


describe("chart theme integration", () => {
  it("reads a valid semantic palette and rejects invalid color input", () => {
    const palette = readChartThemePalette(tokenSource(values), supportsColor);
    expect(palette).toMatchObject({
      surface: "#151813",
      text: "#cbd3c0",
      up: "#9beaa7",
      down: "#ff9a8d",
      focus: "#d8ff38"
    });

    expect(() =>
      readChartThemePalette(
        tokenSource({ ...values, "--chart-grid": "not-a-css-color" }),
        supportsColor
      )
    ).toThrow("Invalid chart theme token: --chart-grid");
  });

  it("applies palette changes to an existing chart and its series", () => {
    const applied = {
      chart: [] as unknown[],
      candlestick: [] as unknown[],
      line: [] as unknown[]
    };
    const palette = readChartThemePalette(tokenSource(values), supportsColor);

    applyChartThemePalette(
      {
        chart: { applyOptions: (options) => applied.chart.push(options) },
        candlestick: { applyOptions: (options) => applied.candlestick.push(options) },
        line: { applyOptions: (options) => applied.line.push(options) }
      },
      palette
    );

    expect(applied.chart).toHaveLength(1);
    expect(applied.candlestick).toHaveLength(1);
    expect(applied.line).toEqual([{ color: "#d8ff38" }]);
  });

  it("reads and applies the global font without recreating the chart", () => {
    const applied: unknown[] = [];
    const font = readChartFontFamily(tokenSource({ "--font-sans": ' "Cascadia Mono", monospace ' }));
    expect(font).toBe('"Cascadia Mono", monospace');
    applyChartFontFamily({ applyOptions: (options) => applied.push(options) }, font);
    expect(applied).toEqual([{ layout: { fontFamily: font } }]);
  });
});
