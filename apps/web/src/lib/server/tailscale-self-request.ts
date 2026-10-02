import { request } from "node:http";
import { isIP } from "node:net";

const SOCKET_PATH = "/var/run/tailscale/tailscaled.sock";
const MAXIMUM_RESPONSE_BYTES = 65_536;
const REQUEST_TIMEOUT_MS = 1_000;

// Tagged nodes have no user identity header. Only the local daemon's own node
// may use this exception; the caller also checks the loopback HTTPS proxy.
export async function isTailscaleSelfRequest(address: string, hostname: string): Promise<boolean> {
  const family = isIP(address);
  if (!family || address.includes("%")) return false;
  try {
    const status = record(await readLocalApi("/localapi/v0/status?peers=false"));
    const self = record(status?.Self);
    if (status?.BackendState !== "Running" || !self ||
        typeof self.ID !== "string" || !self.ID ||
        typeof self.DNSName !== "string" ||
        self.DNSName.replace(/\.$/, "").toLowerCase() !== hostname.toLowerCase() ||
        !Array.isArray(self.TailscaleIPs) || !self.TailscaleIPs.includes(address) ||
        !hasTags(self.Tags)) return false;

    const source = family === 6 ? `[${address}]:1` : `${address}:1`;
    const path = `/localapi/v0/whois?${new URLSearchParams({ addr: source })}`;
    const identity = record(await readLocalApi(path));
    const node = record(identity?.Node);
    return node?.StableID === self.ID && hasTags(node?.Tags);
  } catch {
    return false;
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function hasTags(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0 &&
    value.every((tag) => typeof tag === "string" && tag.startsWith("tag:"));
}

function readLocalApi(path: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let finished = false;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const fail = (cause: Error) => {
      if (finished) return;
      finished = true;
      clearTimeout(deadline);
      reject(cause);
    };
    const client = request({
      socketPath: SOCKET_PATH, hostname: "local-tailscaled.sock", path, method: "GET"
    }, (response) => {
      if (response.statusCode !== 200) {
        fail(new Error("tailscale_local_api_unavailable"));
        response.resume();
        client.destroy();
        return;
      }
      const chunks: Buffer[] = [];
      let bytes = 0;
      response.on("data", (chunk: Buffer) => {
        if (finished) return;
        bytes += chunk.length;
        if (bytes > MAXIMUM_RESPONSE_BYTES) {
          fail(new Error("tailscale_local_api_response_too_large"));
          client.destroy();
          return;
        }
        chunks.push(chunk);
      });
      response.on("error", fail);
      response.on("aborted", () => fail(new Error("tailscale_local_api_aborted")));
      response.on("end", () => {
        if (finished) return;
        try {
          const value = JSON.parse(Buffer.concat(chunks).toString("utf-8")) as unknown;
          finished = true;
          clearTimeout(deadline);
          resolve(value);
        } catch { fail(new Error("tailscale_local_api_invalid_json")); }
      });
    });
    deadline = setTimeout(() => {
      fail(new Error("tailscale_local_api_timeout"));
      client.destroy();
    }, REQUEST_TIMEOUT_MS);
    client.on("error", fail);
    client.end();
  });
}
