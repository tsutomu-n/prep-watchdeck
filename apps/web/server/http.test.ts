import { request, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { gunzipSync } from "node:zlib";
import { setResponse } from "@sveltejs/kit/node";
import { afterEach, expect, test } from "vitest";
import { configureAdapter, createProductionServer, listenOptions } from "./http.mjs";

const servers: Server[] = [];
afterEach(async () => {
  await Promise.all(servers.splice(0).map(server => new Promise<void>((resolve, reject) => {
    server.closeAllConnections();
    server.close(error => error ? reject(error) : resolve());
  })));
});

async function listen(handler: Parameters<typeof createProductionServer>[0], env?: Parameters<typeof createProductionServer>[1]) {
  const server = createProductionServer(handler, env);
  servers.push(server);
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  return (server.address() as AddressInfo).port;
}

function read(port: number, headers: Record<string, string> = {}) {
  return new Promise<{ status: number; headers: import("node:http").IncomingHttpHeaders; body: Buffer }>((resolve, reject) => {
    request({ hostname: "127.0.0.1", port, headers }, response => {
      const chunks: Buffer[] = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode!, headers: response.headers, body: Buffer.concat(chunks) }));
      response.on("error", reject);
    }).on("error", reject).end();
  });
}

test("compresses dynamic JSON without caching it or ignoring gzip opt-out", async () => {
  const payload = JSON.stringify({ rows: Array.from({ length: 200 }, (_, id) => ({ id, value: 123.45 })) });
  const port = await listen((_request, response) => {
    response.setHeader("content-type", "application/json");
    response.setHeader("cache-control", "no-store");
    response.end(payload);
  });
  const compressed = await read(port, { "accept-encoding": "gzip" });
  expect(compressed.headers["content-encoding"]).toBe("gzip");
  expect(compressed.headers.vary).toContain("Accept-Encoding");
  expect(compressed.headers["cache-control"]).toBe("no-store");
  expect(gunzipSync(compressed.body).toString()).toBe(payload);
  expect(compressed.body.length).toBeLessThan(Buffer.byteLength(payload) / 2);
  const plain = await read(port, { "accept-encoding": "gzip;q=0, identity" });
  expect(plain.headers["content-encoding"]).toBeUndefined();
  expect(plain.body.toString()).toBe(payload);
});

test("cancels an adapter response stream when its compressed client disconnects", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) { controller.enqueue(new TextEncoder().encode("x".repeat(8192))); },
    cancel() { cancelled = true; }
  });
  const port = await listen((_request, response) => {
    void setResponse(response, new Response(body, {
      headers: { "content-type": "application/json" }
    }));
  });
  await new Promise<void>((resolve, reject) => {
    const client = request({ hostname: "127.0.0.1", port, headers: { "accept-encoding": "gzip" } }, response => {
      response.once("data", () => { client.destroy(); resolve(); });
    });
    client.on("error", reject);
    client.end();
  });
  await expect.poll(() => cancelled).toBe(true);
});

test("streams an adapter response across chunks and compression backpressure", async () => {
  const chunks = Array.from({ length: 8 }, (_, offset) =>
    Buffer.from(Array.from({ length: 65_536 }, (_, index) => (index * 17 + offset * 31) % 256)));
  let position = 0;
  let drains = 0;
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (position === chunks.length) controller.close();
      else controller.enqueue(chunks[position++]);
    },
    cancel() { cancelled = true; }
  });
  const port = await listen((_request, response) => {
    response.on("drain", () => { drains += 1; });
    void setResponse(response, new Response(body, {
      headers: { "content-type": "application/json" }
    }));
  });
  const result = await read(port, { "accept-encoding": "gzip" });
  expect(result.headers["content-encoding"]).toBe("gzip");
  expect(gunzipSync(result.body)).toEqual(Buffer.concat(chunks));
  expect(position).toBe(chunks.length);
  expect(drains).toBeGreaterThan(0);
  expect(cancelled).toBe(false);
});

test("preserves the socket peer and HTTP origin while retaining Serve identity headers", async () => {
  const port = await listen((request, response) => {
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify({
      protocol: request.headers["x-watchdeck-backend-proto"],
      address: request.socket.remoteAddress,
      forwarded: request.headers["x-forwarded-for"],
      identity: request.headers["tailscale-user-login"]
    }));
  });
  const result = await read(port, {
    "x-watchdeck-backend-proto": "https", "x-forwarded-for": "100.64.0.2",
    "tailscale-user-login": "fixture@example.test"
  });
  expect(JSON.parse(result.body.toString())).toEqual({
    protocol: "http", address: "127.0.0.1", forwarded: "100.64.0.2", identity: "fixture@example.test"
  });
});

test("rejects public listeners and forwarded address overrides", () => {
  expect(() => listenOptions({ HOST: "0.0.0.0", PORT: "5173" })).toThrow();
  expect(() => listenOptions({ PORT: "invalid" })).toThrow();
  expect(() => configureAdapter({ PREP_WATCHDECK_WEB_ADDRESS_HEADER: "x-forwarded-for" })).toThrow();
  const env: Record<string, string> = {};
  configureAdapter(env);
  expect(env.PREP_WATCHDECK_WEB_PROTOCOL_HEADER).toBe("x-watchdeck-backend-proto");
});

test("rejects untrusted Host before dispatch, including read-only routes", async () => {
  let dispatched = 0;
  const port = await listen((_request, response) => {
    dispatched += 1;
    response.end("local data");
  }, { PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN: "https://watchdeck.example.ts.net:8444" });
  for (const host of ["attacker.example", "watchdeck.example.ts.net:8443", "localhost.attacker.example", "user@localhost", "localhost/path"]) {
    expect((await read(port, { host })).status).toBe(403);
  }
  expect(dispatched).toBe(0);
  for (const host of [`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`, "watchdeck.example.ts.net:8444"]) {
    expect((await read(port, { host })).status).toBe(200);
  }
  expect(dispatched).toBe(4);
});
