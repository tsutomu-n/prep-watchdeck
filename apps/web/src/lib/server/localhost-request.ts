import { isTailscaleSelfRequest } from "./tailscale-self-request";

type AddressedRequest = {
  url: URL;
  getClientAddress(): string;
  request?: Request;
};

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const LOOPBACK_ADDRESSES = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

export async function isLocalhostRequest(event: AddressedRequest) {
  return await localRequestOrigin(event) !== null;
}

async function localRequestOrigin(event: AddressedRequest): Promise<string | null> {
  try {
    if (!LOOPBACK_ADDRESSES.has(event.getClientAddress()) ||
        event.request?.headers.has("tailscale-funnel-request")) return null;
    return LOCAL_HOSTS.has(event.url.hostname) ? event.url.origin : await trustedTailscaleOrigin(event);
  } catch {
    return null;
  }
}

// Serve strips client-supplied identity headers and injects the authenticated identity.
// Trust them only on loopback, at the explicitly configured HTTPS origin.
async function trustedTailscaleOrigin(event: AddressedRequest): Promise<string | null> {
  const configured = process.env.PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN;
  if (!configured || !event.request) return null;
  try {
    const origin = new URL(configured);
    if (origin.protocol !== "https:" || !origin.hostname.endsWith(".ts.net") ||
        origin.username || origin.password || origin.pathname !== "/" ||
        origin.search || origin.hash || origin.host !== event.url.host ||
        !["http:", "https:"].includes(event.url.protocol) ||
        !LOOPBACK_ADDRESSES.has(event.getClientAddress())) return null;
    if (event.request.headers.get("tailscale-user-login")?.trim()) return origin.origin;
    // Serve overwrites these proxy headers. Missing identity is permitted only
    // when the local daemon verifies this source as its own tagged node.
    const headers = event.request.headers;
    const address = headers.get("x-forwarded-for")?.trim();
    if (headers.get("x-forwarded-proto") !== "https" ||
        headers.get("x-forwarded-host") !== origin.host || !address ||
        !await isTailscaleSelfRequest(address, origin.hostname)) return null;
    return origin.origin;
  } catch { return null; }
}

export async function hasSameOrigin(event: AddressedRequest & { request: Request }) {
  const expected = await localRequestOrigin(event);
  return expected !== null && event.request.headers.get("origin") === expected;
}

export async function readLocalJson(event: AddressedRequest & { request: Request }, maximum = 65_536) {
  const expected = await localRequestOrigin(event);
  if (expected === null || event.request.headers.get("origin") !== expected) {
    throw new LocalRequestError(403, "local_origin_required");
  }
  if (!/^application\/json(?:\s*;|$)/i.test(event.request.headers.get("content-type") ?? "")) {
    throw new LocalRequestError(400, "json_required");
  }
  const length = Number(event.request.headers.get("content-length"));
  if (Number.isFinite(length) && length > maximum) throw new LocalRequestError(413, "body_too_large");
  const body = await event.request.text();
  if (new TextEncoder().encode(body).length > maximum) {
    throw new LocalRequestError(413, "body_too_large");
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new LocalRequestError(400, "invalid_json");
  }
}

export class LocalRequestError extends Error {
  constructor(public readonly status: number, public readonly code: string) {
    super(code);
  }
}
