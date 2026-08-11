import type { ColorType, IChartApi, ISeriesApi } from "lightweight-charts";

export type ChartThemePalette = {
  surface: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  focus: string;
  volumeUp: string;
  volumeDown: string;
};

export type ChartThemeTargets = {
  chart: Pick<IChartApi, "applyOptions">;
  candlestick: Pick<ISeriesApi<"Candlestick">, "applyOptions">;
  line: Pick<ISeriesApi<"Line">, "applyOptions">;
};

export const chartThemeTokens = {
  surface: "--chart-surface",
  text: "--chart-text",
  grid: "--chart-grid",
  border: "--chart-border",
  up: "--chart-up",
  down: "--chart-down",
  focus: "--chart-focus",
  volumeUp: "--chart-volume-up",
  volumeDown: "--chart-volume-down"
} as const satisfies Record<keyof ChartThemePalette, `--${string}`>;

export const chartFontToken = "--font-sans";

type CssTokenSource = Pick<CSSStyleDeclaration, "getPropertyValue">;
type CssColorSupport = (value: string) => boolean;

export function readChartThemePalette(
  source: CssTokenSource,
  supportsColor: CssColorSupport = supportsCssColor
): ChartThemePalette {
  return {
    surface: readRequiredColorToken(source, chartThemeTokens.surface, supportsColor),
    text: readRequiredColorToken(source, chartThemeTokens.text, supportsColor),
    grid: readRequiredColorToken(source, chartThemeTokens.grid, supportsColor),
    border: readRequiredColorToken(source, chartThemeTokens.border, supportsColor),
    up: readRequiredColorToken(source, chartThemeTokens.up, supportsColor),
    down: readRequiredColorToken(source, chartThemeTokens.down, supportsColor),
    focus: readRequiredColorToken(source, chartThemeTokens.focus, supportsColor),
    volumeUp: readRequiredColorToken(source, chartThemeTokens.volumeUp, supportsColor),
    volumeDown: readRequiredColorToken(source, chartThemeTokens.volumeDown, supportsColor)
  };
}

export function applyChartThemePalette(targets: ChartThemeTargets, palette: ChartThemePalette) {
  targets.chart.applyOptions({
    layout: {
      background: { type: "solid" as ColorType.Solid, color: palette.surface },
      textColor: palette.text
    },
    grid: {
      vertLines: { color: palette.grid },
      horzLines: { color: palette.grid }
    },
    rightPriceScale: { borderColor: palette.border },
    timeScale: { borderColor: palette.border }
  });
  targets.candlestick.applyOptions({
    upColor: palette.up,
    downColor: palette.down,
    borderUpColor: palette.up,
    borderDownColor: palette.down,
    wickUpColor: palette.up,
    wickDownColor: palette.down
  });
  targets.line.applyOptions({ color: palette.focus });
}

export function readChartFontFamily(source: CssTokenSource) {
  const value = source.getPropertyValue(chartFontToken).trim();
  if (!value) throw new Error(`Missing chart font token: ${chartFontToken}`);
  return value;
}

export function applyChartFontFamily(
  chart: Pick<IChartApi, "applyOptions">,
  fontFamily: string
) {
  chart.applyOptions({ layout: { fontFamily } });
}

function readRequiredColorToken(
  source: CssTokenSource,
  token: string,
  supportsColor: CssColorSupport
) {
  const value = source.getPropertyValue(token).trim();
  if (!value) throw new Error(`Missing chart theme token: ${token}`);
  if (!supportsColor(value)) throw new Error(`Invalid chart theme token: ${token}`);
  return value;
}

function supportsCssColor(value: string) {
  return typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("color", value);
}
