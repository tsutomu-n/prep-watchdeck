import { describe, expect, it } from "vitest";
import {
  COLOR_SCHEME_ATTRIBUTE,
  COLOR_SCHEME_CHANGE_EVENT,
  COLOR_SCHEME_STORAGE_KEY,
  colorSchemeGroups,
  colorSchemes,
  defaultColorSchemeId,
  normalizeColorSchemeId,
  readStoredColorScheme,
  writeStoredColorScheme
} from "./color-scheme";

describe("color scheme contract", () => {
  it("keeps the eight schemes in the user-facing order", () => {
    expect(colorSchemes).toEqual([
      { id: "watchdeck", label: "標準", mode: "dark" },
      { id: "carbon-aurora", label: "Carbon Aurora", mode: "dark" },
      { id: "forest-amber", label: "Forest Amber", mode: "dark" },
      { id: "plum-signal", label: "Plum Signal", mode: "dark" },
      { id: "paper-ledger", label: "Paper Ledger", mode: "light" },
      { id: "arctic-terminal", label: "Arctic Terminal", mode: "light" },
      { id: "sage-field", label: "Sage Field", mode: "light" },
      { id: "lilac-current", label: "Lilac Current", mode: "light" }
    ]);
    expect(
      colorSchemeGroups.map((group) => ({
        mode: group.mode,
        label: group.label,
        ids: group.schemes.map((scheme) => scheme.id)
      }))
    ).toEqual([
      {
        mode: "dark",
        label: "ダークテーマ",
        ids: ["watchdeck", "carbon-aurora", "forest-amber", "plum-signal"]
      },
      {
        mode: "light",
        label: "ライトテーマ",
        ids: ["paper-ledger", "arctic-terminal", "sage-field", "lilac-current"]
      }
    ]);
    expect(defaultColorSchemeId).toBe("watchdeck");
  });

  it("publishes stable browser-local interface names", () => {
    expect(COLOR_SCHEME_STORAGE_KEY).toBe("prep-watchdeck:color-scheme");
    expect(COLOR_SCHEME_ATTRIBUTE).toBe("data-color-scheme");
    expect(COLOR_SCHEME_CHANGE_EVENT).toBe("prep-watchdeck:color-scheme-change");
  });

  it("normalizes unknown and empty values to the standard scheme", () => {
    expect(normalizeColorSchemeId("forest-amber")).toBe("forest-amber");
    expect(normalizeColorSchemeId("paper-ledger")).toBe("paper-ledger");
    expect(normalizeColorSchemeId("arctic-terminal")).toBe("arctic-terminal");
    expect(normalizeColorSchemeId("sage-field")).toBe("sage-field");
    expect(normalizeColorSchemeId("lilac-current")).toBe("lilac-current");
    expect(normalizeColorSchemeId("unknown-theme")).toBe("watchdeck");
    expect(normalizeColorSchemeId("")).toBe("watchdeck");
    expect(normalizeColorSchemeId(null)).toBe("watchdeck");
  });

  it("reads a valid saved scheme and fails closed when storage is unavailable", () => {
    expect(readStoredColorScheme({ getItem: () => "plum-signal" })).toBe("plum-signal");
    expect(readStoredColorScheme({ getItem: () => "unknown-theme" })).toBe("watchdeck");
    expect(
      readStoredColorScheme({
        getItem() {
          throw new Error("storage denied");
        }
      })
    ).toBe("watchdeck");
  });

  it("saves normalized values without leaking storage failures", () => {
    const saved: Array<[string, string]> = [];
    expect(
      writeStoredColorScheme(
        {
          setItem(key, value) {
            saved.push([key, value]);
          }
        },
        "carbon-aurora"
      )
    ).toBe(true);
    expect(saved).toEqual([[COLOR_SCHEME_STORAGE_KEY, "carbon-aurora"]]);
    expect(
      writeStoredColorScheme(
        {
          setItem() {
            throw new Error("storage denied");
          }
        },
        "plum-signal"
      )
    ).toBe(false);
  });
});
