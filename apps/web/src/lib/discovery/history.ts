import type { DiscoveryEpisode } from "$lib/generated/discovery-response";

/** Retain already-read pages while replacing episode states from a fresh response. */
export function mergeDiscoveryEpisodes(latest: DiscoveryEpisode[], read: DiscoveryEpisode[]) {
  const byId = new Map(read.map(episode => [episode.id, episode]));
  for (const episode of latest) byId.set(episode.id, episode);
  return [...byId.values()].sort((left, right) => right.firstObservedAt - left.firstObservedAt ||
    right.id.localeCompare(left.id));
}
