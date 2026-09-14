import { describe, expect, it } from "vitest";
import {
  colorSchemes,
  defaultColorSchemeId,
  normalizeColorSchemeId,
  readStoredColorScheme,
  writeStoredColorScheme
} from "./color-scheme";
import {
  defaultFontSchemeId,
  fontSchemes,
  normalizeFontSchemeId,
  readStoredFontScheme,
  writeStoredFontScheme
} from "./font-scheme";


describe("theme preferences", () => {
  it("keeps preference ids unique and defaults selectable", () => {
    const colorIds = colorSchemes.map((scheme) => scheme.id);
    const fontIds = fontSchemes.map((scheme) => scheme.id);

    expect(new Set(colorIds).size).toBe(colorIds.length);
    expect(new Set(fontIds).size).toBe(fontIds.length);
    expect(colorIds).toContain(defaultColorSchemeId);
    expect(fontIds).toContain(defaultFontSchemeId);
    expect(colorSchemes.every((scheme) => scheme.mode === "dark" || scheme.mode === "light")).toBe(true);
  });

  it("normalizes unknown preferences to the current defaults", () => {
    expect(normalizeColorSchemeId("unknown-theme")).toBe(defaultColorSchemeId);
    expect(normalizeColorSchemeId(null)).toBe(defaultColorSchemeId);
    expect(normalizeFontSchemeId("unknown-font")).toBe(defaultFontSchemeId);
    expect(normalizeFontSchemeId(null)).toBe(defaultFontSchemeId);
  });

  it("reads and writes valid preferences without leaking storage failures", () => {
    const color = colorSchemes.at(-1)?.id ?? defaultColorSchemeId;
    const font = fontSchemes.at(-1)?.id ?? defaultFontSchemeId;
    const saved = new Map<string, string>();
    const storage = {
      getItem(key: string) {
        return saved.get(key) ?? null;
      },
      setItem(key: string, value: string) {
        saved.set(key, value);
      }
    };

    expect(writeStoredColorScheme(storage, color)).toBe(true);
    expect(writeStoredFontScheme(storage, font)).toBe(true);
    expect(readStoredColorScheme(storage)).toBe(color);
    expect(readStoredFontScheme(storage)).toBe(font);

    const failingStorage = {
      getItem() {
        throw new Error("storage denied");
      },
      setItem() {
        throw new Error("storage denied");
      }
    };
    expect(readStoredColorScheme(failingStorage)).toBe(defaultColorSchemeId);
    expect(readStoredFontScheme(failingStorage)).toBe(defaultFontSchemeId);
    expect(writeStoredColorScheme(failingStorage, color)).toBe(false);
    expect(writeStoredFontScheme(failingStorage, font)).toBe(false);
  });
});
