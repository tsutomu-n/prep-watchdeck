export const colorSchemes = [
  { id: "watchdeck", label: "標準", mode: "dark" },
  { id: "carbon-aurora", label: "Carbon Aurora", mode: "dark" },
  { id: "forest-amber", label: "Forest Amber", mode: "dark" },
  { id: "plum-signal", label: "Plum Signal", mode: "dark" },
  { id: "paper-ledger", label: "Paper Ledger", mode: "light" },
  { id: "arctic-terminal", label: "Arctic Terminal", mode: "light" },
  { id: "sage-field", label: "Sage Field", mode: "light" },
  { id: "lilac-current", label: "Lilac Current", mode: "light" }
] as const;

export type ColorSchemeId = (typeof colorSchemes)[number]["id"];
export type ColorSchemeMode = (typeof colorSchemes)[number]["mode"];

export const colorSchemeGroups = [
  {
    mode: "dark",
    label: "ダークテーマ",
    schemes: colorSchemes.filter((scheme) => scheme.mode === "dark")
  },
  {
    mode: "light",
    label: "ライトテーマ",
    schemes: colorSchemes.filter((scheme) => scheme.mode === "light")
  }
] as const;

export const defaultColorSchemeId: ColorSchemeId = "watchdeck";
export const COLOR_SCHEME_STORAGE_KEY = "prep-watchdeck:color-scheme";
export const COLOR_SCHEME_ATTRIBUTE = "data-color-scheme";
export const COLOR_SCHEME_CHANGE_EVENT = "prep-watchdeck:color-scheme-change";

type ReadableStorage = Pick<Storage, "getItem">;
type WritableStorage = Pick<Storage, "setItem">;

export function isColorSchemeId(value: unknown): value is ColorSchemeId {
  return colorSchemes.some((scheme) => scheme.id === value);
}

export function normalizeColorSchemeId(value: unknown): ColorSchemeId {
  return isColorSchemeId(value) ? value : defaultColorSchemeId;
}

export function readStoredColorScheme(storage: ReadableStorage): ColorSchemeId {
  try {
    return normalizeColorSchemeId(storage.getItem(COLOR_SCHEME_STORAGE_KEY));
  } catch {
    return defaultColorSchemeId;
  }
}

export function writeStoredColorScheme(storage: WritableStorage, value: unknown): boolean {
  try {
    storage.setItem(COLOR_SCHEME_STORAGE_KEY, normalizeColorSchemeId(value));
    return true;
  } catch {
    return false;
  }
}

export function readDocumentColorScheme(root: Pick<Element, "getAttribute">): ColorSchemeId {
  return normalizeColorSchemeId(root.getAttribute(COLOR_SCHEME_ATTRIBUTE));
}

export function applyDocumentColorScheme(
  root: Pick<Element, "setAttribute">,
  value: unknown
): ColorSchemeId {
  const id = normalizeColorSchemeId(value);
  root.setAttribute(COLOR_SCHEME_ATTRIBUTE, id);
  return id;
}
