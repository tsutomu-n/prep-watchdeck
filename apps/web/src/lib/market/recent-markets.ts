export const RECENT_KEY = "prep-watchdeck:recent-markets-v1";
export const RECENT_CHANGE_EVENT = "prep-watchdeck:recent-changed";

export type RecentMarket = {
  key: string;
  label: string;
  href: string;
  visitedAt: number;
};

export function readRecentMarkets(storage: Pick<Storage, "getItem">): RecentMarket[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(RECENT_KEY) ?? "[]");
    if (!Array.isArray(value)) return [];
    return value.filter((entry): entry is RecentMarket => entry &&
      typeof entry.key === "string" && entry.key.length <= 200 &&
      typeof entry.label === "string" && entry.label.length <= 120 &&
      typeof entry.href === "string" && /^\/(?:\?|rankings\?)/.test(entry.href) &&
      typeof entry.visitedAt === "number" && Number.isFinite(entry.visitedAt)).slice(0, 20);
  } catch { return []; }
}

export function recordRecentMarket(
  storage: Pick<Storage, "getItem" | "setItem">, market: Omit<RecentMarket, "visitedAt">
) {
  try {
    const next = [{ ...market, visitedAt: Date.now() },
      ...readRecentMarkets(storage).filter((entry) => entry.key !== market.key)].slice(0, 20);
    storage.setItem(RECENT_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event(RECENT_CHANGE_EVENT));
  } catch { /* A blocked browser store only disables recent history. */ }
}
