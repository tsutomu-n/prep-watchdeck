import { afterEach, describe, expect, test, vi } from "vitest";
import { isLocalhostRequest, readLocalJson } from "./localhost-request";
import { isTailscaleSelfRequest } from "./tailscale-self-request";

vi.mock("./tailscale-self-request", () => ({ isTailscaleSelfRequest: vi.fn() }));

const ORIGIN = "https://watchdeck.example.ts.net:8444";
afterEach(() => { vi.unstubAllEnvs(); vi.resetAllMocks(); });

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
    expect(await isLocalhostRequest(local)).toBe(true);
    expect(await readLocalJson(local)).toEqual({ action: "invalid" });
    expect(await isLocalhostRequest(event())).toBe(false);
  });

  test("Serve identity at the configured origin permits JSON writes through TLS termination", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    expect(await isLocalhostRequest(event())).toBe(true);
    expect(await readLocalJson(event())).toEqual({ action: "invalid" });
    expect(isTailscaleSelfRequest).not.toHaveBeenCalled();
  });

  test.each([
    ["http://watchdeck.example.ts.net:8444/api/selection", "100.64.0.2", "trader@example.com"],
    ["http://watchdeck.example.ts.net:8444/api/selection", "127.0.0.1", ""],
    ["http://other.example.ts.net:8444/api/selection", "127.0.0.1", "trader@example.com"],
    ["http://watchdeck.example.ts.net:443/api/selection", "127.0.0.1", "trader@example.com"]
  ])("rejects untrusted address, identity or authority: %s %s %s", async (url, address, identity) => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    expect(await isLocalhostRequest(event(url, address, identity))).toBe(false);
  });

  test("remote writes reject missing, cross-origin and backend HTTP origins", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    for (const origin of ["", "https://attacker.example", "http://watchdeck.example.ts.net:8444"]) {
      await expect(readLocalJson(event(undefined, undefined, undefined, origin)))
        .rejects.toMatchObject({ status: 403, code: "local_origin_required" });
    }
  });

  test("malformed or non-HTTPS configuration fails closed", async () => {
    for (const configured of ["invalid", ORIGIN.replace("https:", "http:"), `${ORIGIN}/path`, `${ORIGIN}?x=1`]) {
      vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", configured);
      expect(await isLocalhostRequest(event())).toBe(false);
    }
  });

  test("a daemon-verified tagged self node supports HTTPS reads and same-origin JSON writes", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    vi.mocked(isTailscaleSelfRequest).mockResolvedValue(true);
    const self = selfEvent();
    expect(await isLocalhostRequest(self)).toBe(true);
    expect(isTailscaleSelfRequest).toHaveBeenCalledWith("100.64.0.1", "watchdeck.example.ts.net");
    vi.mocked(isTailscaleSelfRequest).mockClear();
    expect(await readLocalJson(self)).toEqual({ action: "invalid" });
    expect(isTailscaleSelfRequest).toHaveBeenCalledTimes(1);
    for (const origin of ["", "https://attacker.example", ORIGIN.replace("https:", "http:")]) {
      await expect(readLocalJson(selfEvent(origin)))
        .rejects.toMatchObject({ status: 403, code: "local_origin_required" });
    }
  });

  test("missing or inconsistent proxy information and other nodes remain forbidden", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    vi.mocked(isTailscaleSelfRequest).mockResolvedValue(true);
    for (const [key, value] of [
      ["x-forwarded-proto", "http"], ["x-forwarded-host", "other.example.ts.net:8444"],
      ["x-forwarded-for", ""]
    ]) {
      const self = selfEvent();
      self.request.headers.set(key, value);
      expect(await isLocalhostRequest(self)).toBe(false);
    }
    expect(isTailscaleSelfRequest).not.toHaveBeenCalled();
    vi.mocked(isTailscaleSelfRequest).mockResolvedValue(false);
    expect(await isLocalhostRequest(selfEvent())).toBe(false);
    await expect(readLocalJson(selfEvent()))
      .rejects.toMatchObject({ status: 403, code: "local_origin_required" });
  });

  test("Funnel is rejected even with user identity or self proxy information", async () => {
    vi.stubEnv("PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN", ORIGIN);
    vi.mocked(isTailscaleSelfRequest).mockResolvedValue(true);
    for (const candidate of [event(), selfEvent()]) {
      candidate.request.headers.set("tailscale-funnel-request", "?1");
      expect(await isLocalhostRequest(candidate)).toBe(false);
      await expect(readLocalJson(candidate))
        .rejects.toMatchObject({ status: 403, code: "local_origin_required" });
    }
    expect(isTailscaleSelfRequest).not.toHaveBeenCalled();
  });
});

function selfEvent(origin = ORIGIN) {
  const self = event(undefined, undefined, "", origin);
  self.request.headers.set("x-forwarded-proto", "https");
  self.request.headers.set("x-forwarded-host", "watchdeck.example.ts.net:8444");
  self.request.headers.set("x-forwarded-for", "100.64.0.1");
  return self;
}
