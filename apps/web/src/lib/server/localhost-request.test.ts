import { afterEach, describe, expect, test, vi } from "vitest";
import { isLocalhostRequest, readLocalJson } from "./localhost-request";

const ORIGIN = "https://watchdeck.example.ts.net:8444";
afterEach(() => vi.unstubAllEnvs());

function event(url = "http://watchdeck.example.ts.net:8444/api/selection", address = "127.0.0.1",
  identity = "trader@example.com", origin = ORIGIN) {
  return {
    url: new URL(url), getClientAddress: () => address,
    request: new Request(url, { method: "POST", headers: {
      "tailscale-user-login": identity, origin, "content-type": "application/json"
    }, body: '{"action":"invalid"}' })
  };
}

describe("local and authenticated Serve access", () => {
  test("loopback access keeps working without remote configuration", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", "");
    const local = event("http://localhost:5173/api/selection", "127.0.0.1", "", "http://localhost:5173");
    expect(isLocalhostRequest(local)).toBe(true);
    expect(await readLocalJson(local)).toEqual({ action: "invalid" });
    expect(isLocalhostRequest(event())).toBe(false);
  });

  test("Serve identity at the configured origin permits JSON writes through TLS termination", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    expect(isLocalhostRequest(event())).toBe(true);
    expect(await readLocalJson(event())).toEqual({ action: "invalid" });
  });

  test.each([
    ["http://watchdeck.example.ts.net:8444/api/selection", "100.64.0.2", "trader@example.com"],
    ["http://watchdeck.example.ts.net:8444/api/selection", "127.0.0.1", ""],
    ["http://other.example.ts.net:8444/api/selection", "127.0.0.1", "trader@example.com"],
    ["http://watchdeck.example.ts.net:443/api/selection", "127.0.0.1", "trader@example.com"]
  ])("rejects untrusted address, identity or authority: %s %s %s", (url, address, identity) => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    expect(isLocalhostRequest(event(url, address, identity))).toBe(false);
  });

  test("remote writes reject missing, cross-origin and backend HTTP origins", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    for (const origin of ["", "https://attacker.example", "http://watchdeck.example.ts.net:8444"]) {
      await expect(readLocalJson(event(undefined, undefined, undefined, origin)))
        .rejects.toMatchObject({ status: 403, code: "local_origin_required" });
    }
  });

  test("malformed or non-HTTPS configuration fails closed", () => {
    for (const configured of ["invalid", ORIGIN.replace("https:", "http:"), `${ORIGIN}/path`, `${ORIGIN}?x=1`]) {
      vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", configured);
      expect(isLocalhostRequest(event())).toBe(false);
    }
  });
});
