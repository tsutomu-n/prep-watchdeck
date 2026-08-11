import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { colorSchemes } from "./color-scheme";

const css = readFileSync(new URL("../styles/watchdeck-theme.css", import.meta.url), "utf8");
const requiredTokens = [
  "bg",
  "bg-alt",
  "surface",
  "panel",
  "panel-solid",
  "panel-strong",
  "panel-selected",
  "line",
  "line-strong",
  "text",
  "muted",
  "subtle",
  "focus",
  "primary",
  "focus-on",
  "up",
  "down",
  "warning",
  "warning-border",
  "quality-good",
  "quality-risk",
  "chip-line",
  "chip-neutral",
  "chart-surface",
  "chart-text",
  "chart-grid",
  "chart-border",
  "chart-up",
  "chart-down",
  "chart-focus",
  "chart-volume-up",
  "chart-volume-down"
] as const;

function themeBlock(id: string) {
  const selector = id === "watchdeck" ? ":root" : `:root[data-color-scheme="${id}"]`;
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`Missing theme selector: ${selector}`);
  const end = css.indexOf("}", start);
  return css.slice(start, end);
}

function token(block: string, name: string) {
  const match = block.match(new RegExp(`--${name}:\\s*([^;]+);`));
  if (!match?.[1]) throw new Error(`Missing color token: --${name}`);
  return match[1].trim();
}

function hexRgb(value: string) {
  const match = value.match(/^#([0-9a-f]{6})$/i);
  if (!match?.[1]) throw new Error(`Expected six-digit hex color: ${value}`);
  return [0, 2, 4].map((offset) => Number.parseInt(match[1].slice(offset, offset + 2), 16));
}

function luminance(value: string) {
  const channels = hexRgb(value).map((channel) => {
    const normalized = channel / 255;
    return normalized <= 0.04045
      ? normalized / 12.92
      : ((normalized + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}

function contrast(first: string, second: string) {
  const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (lighter! + 0.05) / (darker! + 0.05);
}

describe("color scheme CSS palettes", () => {
  for (const scheme of colorSchemes) {
    it(`${scheme.id} defines every semantic color role`, () => {
      const block = themeBlock(scheme.id);
      for (const name of requiredTokens) expect(token(block, name), name).not.toBe("");
    });

    it(`${scheme.id} preserves text and focus contrast`, () => {
      const block = themeBlock(scheme.id);
      for (const foreground of [
        "text",
        "muted",
        "subtle",
        "up",
        "down",
        "warning",
        "quality-good",
        "quality-risk",
        "chip-neutral"
      ]) {
        expect(
          contrast(token(block, foreground), token(block, "panel-solid")),
          `${foreground} on panel-solid`
        ).toBeGreaterThanOrEqual(4.5);
      }
      expect(contrast(token(block, "focus-on"), token(block, "focus"))).toBeGreaterThanOrEqual(4.5);
      expect(contrast(token(block, "focus"), token(block, "bg-alt"))).toBeGreaterThanOrEqual(3);
    });

    it(`${scheme.id} keeps semantic state colors distinct`, () => {
      const block = themeBlock(scheme.id);
      const stateColors = ["focus", "up", "down", "warning", "quality-good", "quality-risk"].map(
        (name) => token(block, name).toLowerCase()
      );
      expect(new Set(stateColors).size).toBe(stateColors.length);
    });
  }
});
