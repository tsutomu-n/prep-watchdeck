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
