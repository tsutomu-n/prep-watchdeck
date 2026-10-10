import { parseDiscovery, parseDiscoverySummary } from "$lib/discovery/contract";

export class DiscoveryError extends Error {
  constructor(public readonly status: number, public readonly code: string) { super(code); }
}

export class DiscoveryReader {
  constructor(private readonly fetcher: typeof fetch = fetch, private readonly env = process.env) {}
  async read(parameters = new URLSearchParams()) {
    return parseDiscovery(await this.request("discovery", parameters));
  }
  async readSummary(parameters = new URLSearchParams()) {
    if ([...parameters].length) throw new DiscoveryError(400, "discovery_invalid_query");
    return parseDiscoverySummary(await this.request("discovery-summary", parameters));
  }
  private async request(endpoint: "discovery" | "discovery-summary", parameters: URLSearchParams) {
    const rawPort = this.env.PREP_WATCHDECK_ATTENTION_PORT ?? "8770";
    const port = Number(rawPort);
    if (!/^\d+$/.test(rawPort) || port < 1024 || port > 65535 || [5432, 55432, 8769].includes(port)) {
      throw new Error("候補データの接続先が不正です");
    }
    if ([...parameters.keys()].some(key => !["assetId", "cursor", "limit", "generationId"].includes(key)) ||
        parameters.getAll("assetId").length > 4 ||
        parameters.getAll("assetId").some(id => !/^[\p{L}\p{N}:._-]{1,160}$/u.test(id)) ||
        ["cursor", "limit", "generationId"].some(key => parameters.getAll(key).length > 1) ||
        (parameters.has("generationId") && (!parameters.get("generationId") || parameters.get("generationId")!.length > 200 || !parameters.has("assetId"))) ||
        (parameters.has("cursor") && (parameters.get("cursor")!.length > 1000 || !parameters.get("cursor"))) ||
        (parameters.has("limit") && !/^(?:[1-9]|[1-4]\d|50)$/.test(parameters.get("limit")!))) {
      throw new DiscoveryError(400, "discovery_invalid_query");
    }
    const response = await this.fetcher(`http://127.0.0.1:${port}/${endpoint}?${parameters}`, {
      signal: AbortSignal.timeout(5000), redirect: "error", cache: "no-store"
    });
    if (response.status === 409) throw new DiscoveryError(409, "discovery_generation_changed");
    if ((!response.ok && response.status !== 503) || !response.body) throw new Error("候補機能を利用できません");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = []; let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        size += value.byteLength;
        if (size > 32 * 1024 * 1024) throw new Error("候補応答の容量上限を超えました");
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    return JSON.parse(Buffer.concat(chunks).toString("utf-8"));
  }
}
