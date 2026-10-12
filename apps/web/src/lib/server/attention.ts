import { parseAttention } from "$lib/attention/contract";

const MAX_BYTES = 8 * 1024 * 1024;
export class AttentionReader {
  constructor(private readonly fetcher: typeof fetch = fetch, private readonly env = process.env) {}
  async read() {
    const rawPort = this.env.PREP_WATCHDECK_ATTENTION_PORT ?? "8770";
    const port = Number(rawPort);
    if (!/^\d+$/.test(rawPort) || port < 1024 || port > 65535 || [5432, 55432, 8769].includes(port)) {
      throw new Error("注目データの接続先が不正です");
    }
    const response = await this.fetcher(`http://127.0.0.1:${port}/attention`, {
      signal: AbortSignal.timeout(5000), redirect: "error", cache: "no-store"
    });
    if (!response.ok || !response.body) throw new Error("注目データの取得を待っています");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > MAX_BYTES) throw new Error("注目データの応答上限を超えました");
        chunks.push(value);
      }
    } finally { await reader.cancel(); }
    return parseAttention(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
  }
}
