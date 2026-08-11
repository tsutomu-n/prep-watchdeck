import { describe, expect, it } from "vitest";
import {
  FONT_SCHEME_ATTRIBUTE,
  FONT_SCHEME_CHANGE_EVENT,
  FONT_SCHEME_STORAGE_KEY,
  defaultFontSchemeId,
  fontSchemes,
  normalizeFontSchemeId,
  readStoredFontScheme,
  writeStoredFontScheme
} from "./font-scheme";

describe("font scheme contract", () => {
  it("keeps compact and monospace as the only global font choices", () => {
    expect(fontSchemes).toEqual([
      { id: "watchdeck", label: "標準（コンパクト）" },
      { id: "terminal", label: "等幅（ターミナル）" }
    ]);
    expect(defaultFontSchemeId).toBe("watchdeck");
  });

  it("publishes stable browser-local interface names", () => {
    expect(FONT_SCHEME_STORAGE_KEY).toBe("prep-watchdeck:font-scheme");
    expect(FONT_SCHEME_ATTRIBUTE).toBe("data-font-scheme");
    expect(FONT_SCHEME_CHANGE_EVENT).toBe("prep-watchdeck:font-scheme-change");
  });

  it("normalizes unknown and empty values to the standard font", () => {
    expect(normalizeFontSchemeId("terminal")).toBe("terminal");
    expect(normalizeFontSchemeId("readable")).toBe("watchdeck");
    expect(normalizeFontSchemeId("unknown-font")).toBe("watchdeck");
    expect(normalizeFontSchemeId("")).toBe("watchdeck");
    expect(normalizeFontSchemeId(null)).toBe("watchdeck");
  });

  it("reads a valid saved font and fails closed when storage is unavailable", () => {
    expect(readStoredFontScheme({ getItem: () => "terminal" })).toBe("terminal");
    expect(readStoredFontScheme({ getItem: () => "unknown-font" })).toBe("watchdeck");
    expect(
      readStoredFontScheme({
        getItem() {
          throw new Error("storage denied");
        }
      })
    ).toBe("watchdeck");
  });

  it("saves normalized values without leaking storage failures", () => {
    const saved: Array<[string, string]> = [];
    expect(
      writeStoredFontScheme(
        {
          setItem(key, value) {
            saved.push([key, value]);
          }
        },
        "terminal"
      )
    ).toBe(true);
    expect(saved).toEqual([[FONT_SCHEME_STORAGE_KEY, "terminal"]]);
    expect(
      writeStoredFontScheme(
        {
          setItem() {
            throw new Error("storage denied");
          }
        },
        "terminal"
      )
    ).toBe(false);
  });
});
