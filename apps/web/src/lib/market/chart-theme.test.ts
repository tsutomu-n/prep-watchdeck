import { describe, expect, it } from "vitest";
import {
  applyChartFontFamily,
  applyChartThemePalette,
  chartFontToken,
  chartThemeTokens,
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

describe("chart theme palette", () => {
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

  it("keeps the chart semantic roles mapped to their required CSS tokens", () => {
    expect(chartThemeTokens).toEqual({
      surface: "--chart-surface",
      text: "--chart-text",
      grid: "--chart-grid",
      border: "--chart-border",
      up: "--chart-up",
      down: "--chart-down",
      focus: "--chart-focus",
      volumeUp: "--chart-volume-up",
      volumeDown: "--chart-volume-down"
    });
  });

  it("reads and trims every required semantic chart token", () => {
    expect(readChartThemePalette(tokenSource(values), supportsColor)).toEqual({
      surface: "#151813",
      text: "#cbd3c0",
      grid: "#252b22",
      border: "#394034",
      up: "#9beaa7",
      down: "#ff9a8d",
      focus: "#d8ff38",
      volumeUp: "rgba(155, 234, 167, 0.45)",
      volumeDown: "rgba(255, 154, 141, 0.45)"
    });
  });

  it("fails closed with the missing token name", () => {
    for (const token of Object.values(chartThemeTokens)) {
      expect(() =>
        readChartThemePalette(
          tokenSource({
            ...values,
            [token]: "   "
          }),
          supportsColor
        )
      ).toThrow(`Missing chart theme token: ${token}`);
    }
  });

  it("fails closed with the invalid color token name", () => {
    expect(() =>
      readChartThemePalette(
        tokenSource({
          ...values,
          "--chart-grid": "not-a-css-color"
        }),
        supportsColor
      )
    ).toThrow("Invalid chart theme token: --chart-grid");
  });

  it("recolors an existing chart and series without recreating them", () => {
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

    expect(applied.chart).toEqual([
      {
        layout: {
          background: { type: "solid", color: "#151813" },
          textColor: "#cbd3c0"
        },
        grid: {
          vertLines: { color: "#252b22" },
          horzLines: { color: "#252b22" }
        },
        rightPriceScale: { borderColor: "#394034" },
        timeScale: { borderColor: "#394034" }
      }
    ]);
    expect(applied.candlestick).toEqual([
      {
        upColor: "#9beaa7",
        downColor: "#ff9a8d",
        borderUpColor: "#9beaa7",
        borderDownColor: "#ff9a8d",
        wickUpColor: "#9beaa7",
        wickDownColor: "#ff9a8d"
      }
    ]);
    expect(applied.line).toEqual([{ color: "#d8ff38" }]);
  });

  it("reads and applies the global font without recreating the chart", () => {
    const applied: unknown[] = [];
    expect(chartFontToken).toBe("--font-sans");
    expect(readChartFontFamily(tokenSource({ "--font-sans": ' "Cascadia Mono", monospace ' }))).toBe(
      '"Cascadia Mono", monospace'
    );
    applyChartFontFamily(
      { applyOptions: (options) => applied.push(options) },
      '"Cascadia Mono", monospace'
    );
    expect(applied).toEqual([{ layout: { fontFamily: '"Cascadia Mono", monospace' } }]);
  });

  it("fails closed when the global chart font token is missing", () => {
    expect(() => readChartFontFamily(tokenSource({ "--font-sans": "   " }))).toThrow(
      "Missing chart font token: --font-sans"
    );
  });
});
