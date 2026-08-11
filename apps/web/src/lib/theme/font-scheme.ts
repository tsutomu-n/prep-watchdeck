export const fontSchemes = [
  { id: "watchdeck", label: "標準（コンパクト）" },
  { id: "terminal", label: "等幅（ターミナル）" }
] as const;

export type FontSchemeId = (typeof fontSchemes)[number]["id"];

export const defaultFontSchemeId: FontSchemeId = "watchdeck";
export const FONT_SCHEME_STORAGE_KEY = "prep-watchdeck:font-scheme";
export const FONT_SCHEME_ATTRIBUTE = "data-font-scheme";
export const FONT_SCHEME_CHANGE_EVENT = "prep-watchdeck:font-scheme-change";

type ReadableStorage = Pick<Storage, "getItem">;
type WritableStorage = Pick<Storage, "setItem">;

export function isFontSchemeId(value: unknown): value is FontSchemeId {
  return fontSchemes.some((scheme) => scheme.id === value);
}

export function normalizeFontSchemeId(value: unknown): FontSchemeId {
  return isFontSchemeId(value) ? value : defaultFontSchemeId;
}

export function readStoredFontScheme(storage: ReadableStorage): FontSchemeId {
  try {
    return normalizeFontSchemeId(storage.getItem(FONT_SCHEME_STORAGE_KEY));
  } catch {
    return defaultFontSchemeId;
  }
}

export function writeStoredFontScheme(storage: WritableStorage, value: unknown): boolean {
  try {
    storage.setItem(FONT_SCHEME_STORAGE_KEY, normalizeFontSchemeId(value));
    return true;
  } catch {
    return false;
  }
}

export function readDocumentFontScheme(root: Pick<Element, "getAttribute">): FontSchemeId {
  return normalizeFontSchemeId(root.getAttribute(FONT_SCHEME_ATTRIBUTE));
}

export function applyDocumentFontScheme(
  root: Pick<Element, "setAttribute">,
  value: unknown
): FontSchemeId {
  const id = normalizeFontSchemeId(value);
  root.setAttribute(FONT_SCHEME_ATTRIBUTE, id);
  return id;
}
