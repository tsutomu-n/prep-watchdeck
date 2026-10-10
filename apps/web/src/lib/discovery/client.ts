import { parseDiscovery, parseDiscoverySummary } from "./contract";

export class DiscoveryGenerationChanged extends Error {
  constructor() { super("候補の更新待ちです。根拠が同じ世代に揃うまで判断・実Venueの確認を待ってください。"); }
}
export async function requestDiscovery(parameters = new URLSearchParams(), fetcher: typeof fetch = fetch) {
  const response = await fetcher(`/api/discovery?${parameters}`, { cache: "no-store" });
  if (response.status === 409) throw new DiscoveryGenerationChanged();
  if (!response.ok) throw new Error("候補機能を利用できません。Attentionの対応版と稼働状態を確認してください。");
  return parseDiscovery(await response.json());
}

/** Publish only a complete summary + at most four details from one generation. */
export async function readDiscoveryView(assetIds: string[], fetcher: typeof fetch = fetch) {
  if (assetIds.length > 4 || new Set(assetIds).size !== assetIds.length) throw new Error("比較は最大4件です");
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const response = await fetcher("/api/discovery-summary", { cache: "no-store" });
      if (!response.ok) throw new Error("候補機能を利用できません。Attentionの対応版と稼働状態を確認してください。");
      const summary = parseDiscoverySummary(await response.json());
      if (!assetIds.length || summary.generationId === null) return { summary, detail: null };
      const query = new URLSearchParams({ generationId: summary.generationId });
      assetIds.forEach(id => query.append("assetId", id));
      const detail = await requestDiscovery(query, fetcher);
      if (detail.rows.length > assetIds.length || detail.rows.some(row => !assetIds.includes(row.assetId))) {
        throw new Error("比較対象以外の根拠が返されました");
      }
      if (detail.generationId !== summary.generationId || detail.decisionAt !== summary.decisionAt ||
          detail.rankingCutoff !== summary.rankingCutoff || detail.status !== summary.status ||
          detail.reason !== summary.reason || detail.rows.some(row => {
            const label = summary.rows.find(item => item.assetId === row.assetId);
            return !label || label.identityKey !== row.identityKey || label.state !== row.state ||
              label.direction !== row.direction || label.confirmation !== row.confirmation ||
              label.episodeId !== row.episodeId || label.reason !== row.reason ||
              label.referenceKey !== row.referenceKey || JSON.stringify(label.originals) !== JSON.stringify(row.originals);
          })) throw new DiscoveryGenerationChanged();
      return { summary, detail };
    } catch (cause) {
      if (!(cause instanceof DiscoveryGenerationChanged) || attempt === 1) throw cause;
    }
  }
  throw new DiscoveryGenerationChanged();
}
