import { EventEmitter } from "node:events";
import { request, type ClientRequest, type IncomingMessage, type RequestOptions } from "node:http";
import { afterEach, describe, expect, test, vi } from "vitest";
import { isTailscaleSelfRequest } from "./tailscale-self-request";

vi.mock("node:http", () => ({ request: vi.fn() }));
afterEach(() => { vi.resetAllMocks(); vi.useRealTimers(); });

const ADDRESS = "100.64.0.1";
const HOSTNAME = "watchdeck.example.ts.net";
const STATUS = {
  BackendState: "Running", Self: {
    ID: "self-node", DNSName: `${HOSTNAME}.`, Tags: ["tag:server"],
    TailscaleIPs: [ADDRESS, "fd7a:115c:a1e0::1"]
  }
};
const IDENTITY = { Node: { StableID: "self-node", Tags: ["tag:server"] } };

type Reply = {
  body?: unknown; raw?: string; chunks?: string[]; status?: number; error?: boolean;
  hang?: boolean; aborted?: boolean; responseError?: boolean; closeBeforeEnd?: boolean;
};

function replies(...values: Reply[]) {
  vi.mocked(request).mockImplementation((...args) => {
    const callback = args.find((value) => typeof value === "function") as
      (response: IncomingMessage) => void;
    const value = values.shift();
    const client = new EventEmitter() as ClientRequest;
    client.destroy = ((cause?: Error) => {
      queueMicrotask(() => { if (cause) client.emit("error", cause); client.emit("close"); });
      return client;
    }) as typeof client.destroy;
    client.end = (() => {
      queueMicrotask(() => {
        if (!value || value.error) { client.destroy(new Error("socket unavailable")); return; }
        if (value.hang) return;
        const response = new EventEmitter() as IncomingMessage;
        response.statusCode = value.status ?? 200;
        response.resume = (() => response) as typeof response.resume;
        callback(response);
        if (response.statusCode === 200) {
          for (const chunk of value.chunks ?? [value.raw ?? JSON.stringify(value.body)]) {
            response.emit("data", Buffer.from(chunk));
          }
          if (value.aborted) response.emit("aborted");
          if (value.responseError) response.emit("error", new Error("response failed"));
          if (value.closeBeforeEnd) client.emit("close");
          response.emit("end");
          client.emit("close");
        }
      });
      return client;
    }) as typeof client.end;
    return client;
  });
}

describe("Tailscale self identity through the local Unix socket", () => {
  test.each([ADDRESS, "fd7a:115c:a1e0::1"])("accepts the verified tagged self node at %s", async (address) => {
    replies({ body: STATUS, closeBeforeEnd: true }, { body: IDENTITY, closeBeforeEnd: true });
    expect(await isTailscaleSelfRequest(address, HOSTNAME)).toBe(true);
    const calls = vi.mocked(request).mock.calls;
    const options = calls.map((call) => call[0] as RequestOptions);
    expect(options.every((value) => value.socketPath === "/var/run/tailscale/tailscaled.sock" &&
      value.method === "GET" && value.hostname === "local-tailscaled.sock")).toBe(true);
    expect(options[0].path).toBe("/localapi/v0/status?peers=false");
    const whois = new URL(options[1].path!, "http://local");
    expect(whois.searchParams.get("addr")).toBe(address.includes(":") ? `[${address}]:1` : `${address}:1`);
  });

  test("rejects malformed or chained source addresses without contacting the daemon", async () => {
    for (const address of ["", "hostname", `${ADDRESS}, 100.64.0.2`, "127.0.0.1:80", "fe80::1%lo"]) {
      expect(await isTailscaleSelfRequest(address, HOSTNAME)).toBe(false);
    }
    expect(request).not.toHaveBeenCalled();
  });

  test("rejects remote source IPs, mismatched hostnames, stopped and malformed daemon state", async () => {
    for (const status of [
      { ...STATUS, BackendState: "Stopped" },
      { ...STATUS, Self: { ...STATUS.Self, TailscaleIPs: ["100.64.0.2"] } },
      { ...STATUS, Self: { ...STATUS.Self, DNSName: "other.example.ts.net." } },
      { ...STATUS, Self: { ...STATUS.Self, ID: "" } },
      { ...STATUS, Self: { ...STATUS.Self, Tags: [] } },
      null, [], { Self: null }
    ]) {
      vi.mocked(request).mockClear();
      replies({ body: status });
      expect(await isTailscaleSelfRequest(ADDRESS, HOSTNAME)).toBe(false);
      expect(request).toHaveBeenCalledTimes(1);
    }
  });

  test("rejects a different or unverified WhoIs node even at a self address", async () => {
    for (const identity of [
      { Node: { ...IDENTITY.Node, StableID: "another-node" } },
      { Node: { StableID: "self-node", Tags: [] } },
      null, { Node: null }, { Node: {} }
    ]) {
      replies({ body: STATUS }, { body: identity });
      expect(await isTailscaleSelfRequest(ADDRESS, HOSTNAME)).toBe(false);
    }
  });

  test("socket failures, non-success responses, invalid JSON and oversized bodies fail closed", async () => {
    for (const reply of [
      { error: true }, { status: 403 }, { raw: "not-json" },
      { raw: JSON.stringify({ ...STATUS, ...IDENTITY, extra: "x".repeat(65_536) }) }
    ]) {
      replies(reply);
      expect(await isTailscaleSelfRequest(ADDRESS, HOSTNAME)).toBe(false);
      replies({ body: STATUS }, reply);
      expect(await isTailscaleSelfRequest(ADDRESS, HOSTNAME)).toBe(false);
    }
  });

  test("an unresponsive daemon times out and denies access", async () => {
    vi.useFakeTimers();
    replies({ hang: true });
    const result = isTailscaleSelfRequest(ADDRESS, HOSTNAME);
    await vi.advanceTimersByTimeAsync(1_000);
    expect(await result).toBe(false);
  });

  test.each(["oversized", "aborted", "error"])("a valid prefix cannot override %s failure at end", async (failure) => {
    for (const phase of ["status", "whois"]) {
      const reply: Reply = {
        chunks: [JSON.stringify(phase === "status" ? STATUS : IDENTITY)],
        aborted: failure === "aborted", responseError: failure === "error"
      };
      if (failure === "oversized") reply.chunks!.push(" ".repeat(65_537));
      replies(...(phase === "status" ? [reply] : [{ body: STATUS }, reply]));
      expect(await isTailscaleSelfRequest(ADDRESS, HOSTNAME)).toBe(false);
    }
  });
});
