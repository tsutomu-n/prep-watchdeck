type AddressedRequest = {
  url: URL;
  getClientAddress(): string;
  request?: Request;
};

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const LOOPBACK_ADDRESSES = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

export function isLocalhostRequest(event: AddressedRequest) {
  try {
    if (!LOOPBACK_ADDRESSES.has(event.getClientAddress())) return false;
    return LOCAL_HOSTS.has(event.url.hostname) || trustedTailscaleOrigin(event) !== null;
  } catch {
    return false;
  }
}

// Serve strips client-supplied identity headers and injects the authenticated identity.
// Trust them only on loopback, at the explicitly configured HTTPS origin.
function trustedTailscaleOrigin(event: AddressedRequest): string | null {
  const configured = process.env.PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN;
  if (!configured || !event.request?.headers.get("tailscale-user-login")?.trim()) return null;
  try {
    const origin = new URL(configured);
    if (origin.protocol !== "https:" || !origin.hostname.endsWith(".ts.net") ||
        origin.username || origin.password || origin.pathname !== "/" ||
        origin.search || origin.hash || origin.host !== event.url.host ||
        !["http:", "https:"].includes(event.url.protocol) ||
        !LOOPBACK_ADDRESSES.has(event.getClientAddress())) return null;
    return origin.origin;
  } catch { return null; }
}

export function hasSameOrigin(event: AddressedRequest & { request: Request }) {
  const expected = trustedTailscaleOrigin(event) ?? event.url.origin;
  return event.request.headers.get("origin") === expected;
}

export async function readLocalJson(event: AddressedRequest & { request: Request }, maximum = 65_536) {
  if (!isLocalhostRequest(event) || !hasSameOrigin(event)) {
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
