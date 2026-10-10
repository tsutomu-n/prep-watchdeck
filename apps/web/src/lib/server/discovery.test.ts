import { expect, test, vi } from "vitest";
import { discoveryFixture } from "$lib/discovery/discovery-test-fixture";
import { DiscoveryReader } from "./discovery";

test("discovery proxy uses only configured loopback and handles an older Attention endpoint or malformed query", async () => {
  const fetcher = vi.fn(async (_input: string | URL | Request) => new Response(JSON.stringify(discoveryFixture()), { headers: { "content-type": "application/json" } }));
  const reader = new DiscoveryReader(fetcher, { PREP_WATCHDECK_ATTENTION_PORT: "18870" });
  const parameters = new URLSearchParams(); parameters.append("assetId", "asset:BTC"); parameters.append("assetId", "asset:ETH");
  const result = await reader.read(parameters);
  expect(result.rows.length).toBe(5);
  expect(fetcher.mock.calls[0][0]).toBe("http://127.0.0.1:18870/discovery?assetId=asset%3ABTC&assetId=asset%3AETH");
  for (const query of ["url=https://example.com", "limit=51", "cursor=", "assetId=../bad", "assetId=a&assetId=b&assetId=c&assetId=d&assetId=e"]) {
    await expect(reader.read(new URLSearchParams(query))).rejects.toThrow();
  }
  expect(fetcher).toHaveBeenCalledTimes(1);
  await expect(new DiscoveryReader(async () => new Response("not found", { status: 404 })).read()).rejects.toThrow();
  await expect(new DiscoveryReader(fetcher, { PREP_WATCHDECK_ATTENTION_PORT: "5432" }).read()).rejects.toThrow();
});

test("discovery queries preserve Unicode market identities as one encoded asset parameter", async () => {
  const parameters = new URLSearchParams({ assetId: "crypto:币安人生" });
  const reader = new DiscoveryReader(async input => {
    const url = new URL(String(input));
    expect(url.origin).toBe("http://127.0.0.1:18870");
    expect([...url.searchParams]).toEqual([["assetId", "crypto:币安人生"]]);
    return new Response(JSON.stringify(discoveryFixture()));
  }, { PREP_WATCHDECK_ATTENTION_PORT: "18870" });
  expect((await reader.read(parameters)).rows).toHaveLength(5);
});
