import { createServer } from "node:http";
import compression from "compression";

const PROTOCOL_HEADER = "x-watchdeck-backend-proto";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** @param {string | undefined} authority */
function hostUrl(authority) {
  if (!authority) return null;
  try {
    const url = new URL(`http://${authority}`);
    return url.username || url.password || url.pathname !== "/" || url.search || url.hash ? null : url;
  } catch { return null; }
}

/** @param {Record<string, string | undefined>} env */
export function configureAdapter(env) {
  // Keep the existing socket-based authentication boundary. Serve's forwarded
  // identity is verified by localhost-request, not by the adapter's peer lookup.
  for (const key of ["ORIGIN", "ADDRESS_HEADER", "HOST_HEADER", "PORT_HEADER"]) {
    if (env[`PREP_WATCHDECK_WEB_${key}`]) {
      throw new Error(`PREP_WATCHDECK_WEB_${key} cannot override the local Web boundary`);
    }
  }
  env.PREP_WATCHDECK_WEB_PROTOCOL_HEADER = PROTOCOL_HEADER;
}

/** @param {Record<string, string | undefined>} env */
export function listenOptions(env) {
  const host = env.HOST ?? "127.0.0.1";
  const rawPort = env.PORT ?? "5173";
  const port = Number(rawPort);
  if (!["127.0.0.1", "::1"].includes(host)) throw new Error("Web HOST must be loopback");
  if (!/^\d+$/.test(rawPort) || !Number.isSafeInteger(port) || port < 0 || port > 65535) {
    throw new Error("Web PORT must be an integer between 0 and 65535");
  }
  return { host, port };
}

/**
 * @param {import("node:http").RequestListener} handler
 * @param {{ PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN?: string }} [env]
 */
export function createProductionServer(handler, env = process.env) {
  let trustedHost = null;
  try {
    const origin = new URL(env.PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN ?? "");
    if (origin.protocol === "https:" && origin.hostname.endsWith(".ts.net") &&
        !origin.username && !origin.password && origin.pathname === "/" && !origin.search && !origin.hash) {
      trustedHost = origin.host;
    }
  } catch { /* Without a valid configured origin only loopback hosts are allowed. */ }
  // The middleware uses the standard Node request/response API; its published
  // declarations require Express-specific fields that this handler does not use.
  const compress = /** @type {(request: import("node:http").IncomingMessage,
    response: import("node:http").ServerResponse, next: () => void) => void} */ (compression());
  return createServer((request, response) => {
    // Keep Vite's host boundary when replacing its server. Some read-only routes
    // rely on this listener guard; a loopback socket alone does not stop DNS rebinding.
    const url = hostUrl(request.headers.host);
    if (!url || (!LOCAL_HOSTS.has(url.hostname) && url.host !== trustedHost)) {
      response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" });
      response.end("Forbidden host");
      return;
    }
    // This listener is HTTP even when Serve terminates HTTPS. Retain that same
    // backend URL behavior as Vite, and never trust this header from a client.
    request.headers[PROTOCOL_HEADER] = "http";
    response.setHeader("Vary", "Accept-Encoding");
    response.setHeader("Cache-Control", "no-store");
    compress(request, response, () => handler(request, response));
  });
}
