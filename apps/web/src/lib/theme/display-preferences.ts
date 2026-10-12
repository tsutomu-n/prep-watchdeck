import {
  DEFAULT_REFERENCE_TIME,
  REFERENCE_TIME_STORAGE_KEY,
  isReferenceTime,
  readStoredReferenceTime,
  writeStoredReferenceTime
} from "$lib/market/price-change";
import { DEFAULT_TURNOVER_DECIMALS, isTurnoverDecimals } from "$lib/market/turnover-format";

export const REFERENCE_TIME_CHANGE_EVENT = "prep-watchdeck:daily-change-reference-change";

let sessionReferenceTime: string | null = null;

function readReferenceTime(): string {
  if (typeof window === "undefined") return DEFAULT_REFERENCE_TIME;
  if (sessionReferenceTime !== null) return sessionReferenceTime;
  try {
    sessionReferenceTime = readStoredReferenceTime(window.localStorage);
  } catch {
    sessionReferenceTime = DEFAULT_REFERENCE_TIME;
  }
  return sessionReferenceTime;
}

/** Applies immediately, including SPA navigation when browser storage is unavailable. */
export function setReferenceTime(value: string): boolean {
  if (!isReferenceTime(value) || typeof window === "undefined") return false;
  sessionReferenceTime = value;
  let saved = false;
  try {
    saved = writeStoredReferenceTime(window.localStorage, value);
  } catch {
    // Accessing localStorage itself can be denied by the browser.
  }
  window.dispatchEvent(new CustomEvent(REFERENCE_TIME_CHANGE_EVENT, { detail: { value } }));
  return saved;
}

export function subscribeReferenceTime(listener: (value: string) => void): () => void {
  listener(readReferenceTime());
  if (typeof window === "undefined") return () => {};

  function syncChange(event: Event) {
    const value: unknown = (event as CustomEvent<{ value?: unknown }>).detail?.value;
    if (!isReferenceTime(value)) return;
    sessionReferenceTime = value;
    listener(value);
  }
  function syncStorage(event: StorageEvent) {
    if (event.key !== REFERENCE_TIME_STORAGE_KEY && event.key !== null) return;
    sessionReferenceTime = isReferenceTime(event.newValue) ? event.newValue : DEFAULT_REFERENCE_TIME;
    listener(sessionReferenceTime);
  }
  window.addEventListener(REFERENCE_TIME_CHANGE_EVENT, syncChange);
  window.addEventListener("storage", syncStorage);
  return () => {
    window.removeEventListener(REFERENCE_TIME_CHANGE_EVENT, syncChange);
    window.removeEventListener("storage", syncStorage);
  };
}

export const TURNOVER_DECIMALS_KEY = "prep-watchdeck:turnover-decimals";
const TURNOVER_DECIMALS_EVENT = "prep-watchdeck:turnover-decimals-change";
let sessionTurnoverDecimals: number | null = null;

function storedTurnoverDecimals(value: string | null): number {
  return value !== null && /^[0-4]$/.test(value) ? Number(value) : DEFAULT_TURNOVER_DECIMALS;
}

export function setTurnoverDecimals(value: number): boolean {
  if (!isTurnoverDecimals(value) || typeof window === "undefined") return false;
  sessionTurnoverDecimals = value;
  let saved = false;
  try {
    window.localStorage.setItem(TURNOVER_DECIMALS_KEY, String(value));
    saved = true;
  } catch { /* Keep the preference for SPA navigation when storage is denied. */ }
  window.dispatchEvent(new CustomEvent(TURNOVER_DECIMALS_EVENT, { detail: { value } }));
  return saved;
}

export function subscribeTurnoverDecimals(listener: (value: number) => void): () => void {
  if (typeof window === "undefined") {
    listener(DEFAULT_TURNOVER_DECIMALS);
    return () => {};
  }
  if (sessionTurnoverDecimals === null) {
    try { sessionTurnoverDecimals = storedTurnoverDecimals(window.localStorage.getItem(TURNOVER_DECIMALS_KEY)); }
    catch { sessionTurnoverDecimals = DEFAULT_TURNOVER_DECIMALS; }
  }
  listener(sessionTurnoverDecimals);
  function change(event: Event) {
    const value: unknown = (event as CustomEvent<{ value?: unknown }>).detail?.value;
    if (!isTurnoverDecimals(value)) return;
    sessionTurnoverDecimals = value;
    listener(value);
  }
  function storage(event: StorageEvent) {
    if (event.key !== TURNOVER_DECIMALS_KEY && event.key !== null) return;
    sessionTurnoverDecimals = storedTurnoverDecimals(event.newValue);
    listener(sessionTurnoverDecimals);
  }
  window.addEventListener(TURNOVER_DECIMALS_EVENT, change);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(TURNOVER_DECIMALS_EVENT, change);
    window.removeEventListener("storage", storage);
  };
}
