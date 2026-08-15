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
