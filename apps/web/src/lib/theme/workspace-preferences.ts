import { get, readonly, writable } from "svelte/store";

export const WORKSPACE_PREFERENCES_KEY = "prep-watchdeck:workspace-preferences:v2";
const LEGACY_PREFERENCES_KEY = "prep-watchdeck:workspace-preferences:v1";
export const defaultPreferences = {
  layout: "normal" as "normal" | "ultra",
  textSize: "auto" as "auto" | "small" | "standard" | "large",
  rowSpacing: "auto" as "auto" | "compact" | "standard" | "comfortable",
  percentDecimals: 2,
  ratioDecimals: 1,
  quantityDecimals: 2,
  turnoverNotation: "compact" as "compact" | "full",
  initialPage: "reference" as "reference" | "native",
  initialPeriod: "default" as "default" | "15m" | "1h" | "24h" | "daily",
  initialOrder: "default" as "default" | "gainers" | "losers" | "turnover",
  initialColumns: "standard" as "standard" | "movement",
  referenceViewId: "",
  nativeViewId: "",
  surgeRatio: 3,
  directionPct: 2,
  chartInterval: "last" as "last" | "5" | "15" | "60" | "240" | "D",
  chartVolume: true
};
export type WorkspacePreferences = typeof defaultPreferences;
export function getDefaultPreferences(): WorkspacePreferences {
  const mobile = typeof window !== "undefined" && window.matchMedia("(max-width: 48rem)").matches;
  return { ...defaultPreferences, layout: mobile ? "ultra" : "normal" };
}
const options = {
  layout: ["normal", "ultra"], textSize: ["auto", "small", "standard", "large"],
  rowSpacing: ["auto", "compact", "standard", "comfortable"], turnoverNotation: ["compact", "full"],
  initialPage: ["reference", "native"], initialPeriod: ["default", "15m", "1h", "24h", "daily"],
  initialOrder: ["default", "gainers", "losers", "turnover"], initialColumns: ["standard", "movement"],
  chartInterval: ["last", "5", "15", "60", "240", "D"]
};

/** Untrusted local storage is never allowed to turn missing data into a signal. */
export function normalizePreferences(input: unknown): WorkspacePreferences {
  const result = getDefaultPreferences();
  if (!input || typeof input !== "object" || Array.isArray(input)) return result;
  const source = input as Record<string, unknown>;
  for (const key of Object.keys(options) as (keyof typeof options)[]) {
    const value = source[key];
    if (typeof value === "string" && (options[key] as readonly string[]).includes(value)) {
      Object.assign(result, { [key]: value });
    }
  }
  for (const key of ["percentDecimals", "ratioDecimals", "quantityDecimals"] as const) {
    const value = source[key];
    if (typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 6) result[key] = value;
  }
  for (const [key, min, max] of [["surgeRatio", 1, 1000], ["directionPct", 0.01, 100]] as const) {
    const value = source[key];
    if (typeof value === "number" && Number.isFinite(value) && value >= min && value <= max) result[key] = value;
  }
  for (const key of ["referenceViewId", "nativeViewId"] as const) {
    if (typeof source[key] === "string" && /^(?:[A-Za-z0-9_-]{1,64})?$/.test(source[key])) result[key] = source[key];
  }
  if (typeof source.chartVolume === "boolean") result.chartVolume = source.chartVolume;
  return result;
}
export function parsePreferences(raw: string | null): WorkspacePreferences {
  try { return normalizePreferences(raw === null ? null : JSON.parse(raw)); }
  catch { return getDefaultPreferences(); }
}
/** Retired layouts use the device default; unrelated preferences survive. */
export function readPreferences(current: string | null, legacy: string | null): WorkspacePreferences {
  if (current !== null) return parsePreferences(current);
  return { ...parsePreferences(legacy), layout: getDefaultPreferences().layout };
}
const state = writable<WorkspacePreferences>({ ...defaultPreferences });
export const preferences = readonly(state);
let initialized = false;
function apply(value: WorkspacePreferences) {
  state.set(value);
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.layout = value.layout;
  root.dataset.textSize = value.textSize;
  root.dataset.rowSpacing = value.rowSpacing;
}
export function currentPreferences(): WorkspacePreferences {
  if (typeof window === "undefined") return { ...defaultPreferences };
  if (!initialized) {
    let value = getDefaultPreferences();
    try { value = readPreferences(window.localStorage.getItem(WORKSPACE_PREFERENCES_KEY), window.localStorage.getItem(LEGACY_PREFERENCES_KEY)); } catch { /* Defaults remain usable. */ }
    apply(value); initialized = true;
  }
  return get(state);
}
export function initializePreferences(): () => void {
  if (typeof window === "undefined") return () => {};
  currentPreferences();
  const sync = (event: StorageEvent) => {
    if (event.key === WORKSPACE_PREFERENCES_KEY || event.key === null) apply(parsePreferences(event.newValue));
  };
  window.addEventListener("storage", sync);
  return () => window.removeEventListener("storage", sync);
}
export function setPreferences(patch: Partial<WorkspacePreferences>): boolean {
  if (typeof window === "undefined") return false;
  const value = normalizePreferences({ ...get(state), ...patch });
  apply(value); initialized = true;
  try { window.localStorage.setItem(WORKSPACE_PREFERENCES_KEY, JSON.stringify(value)); return true; }
  catch { return false; }
}

export function nativeChartInterval(value: WorkspacePreferences["chartInterval"]) {
  return ({ last: "15m", "5": "5m", "15": "15m", "60": "1h", "240": "4h", D: "24h" } as const)[value];
}
