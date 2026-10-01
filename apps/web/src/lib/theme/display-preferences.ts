import {
  DEFAULT_REFERENCE_TIME,
  REFERENCE_TIME_STORAGE_KEY,
  isReferenceTime,
  readStoredReferenceTime,
  writeStoredReferenceTime
} from "$lib/market/price-change";

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
