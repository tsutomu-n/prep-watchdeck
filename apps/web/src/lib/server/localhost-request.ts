type AddressedRequest = {
  url: URL;
  getClientAddress(): string;
};

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);
const LOOPBACK_ADDRESSES = new Set(["127.0.0.1", "::1", "::ffff:127.0.0.1"]);

export function isLocalhostRequest(event: AddressedRequest) {
  if (!LOCAL_HOSTS.has(event.url.hostname)) return false;
  try {
    return LOOPBACK_ADDRESSES.has(event.getClientAddress());
  } catch {
    return false;
  }
}

export function hasSameOrigin(event: { url: URL; request: Request }) {
  return event.request.headers.get("origin") === event.url.origin;
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
