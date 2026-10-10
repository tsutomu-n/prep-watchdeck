import { expect, test, vi } from "vitest";
import { DiscoveryGenerationChanged, readDiscoveryView } from "./client";
import { comparisonPin } from "./contract";
import { discoveryFixture, discoverySummaryFixture } from "./discovery-test-fixture";

function detail(generationId: string) {
  const value = discoveryFixture();
  return { ...value, rows: value.rows.slice(0, 1), generationId, inputs: value.inputs && { ...value.inputs, generationId } };
}
function summary(generationId: string) { return { ...discoverySummaryFixture(), generationId }; }

test("poll requests summary and at most four details without a full-universe detail read", async () => {
  const ids = ["asset:BTC", "asset:ETH", "asset:SOL", "asset:MISSING"];
  const fetcher = vi.fn(async input => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("discovery-summary")) return new Response(JSON.stringify(summary("g")));
    expect(url.searchParams.getAll("assetId")).toEqual(ids);
    expect(url.searchParams.get("generationId")).toBe("g");
    const response = detail("g"); response.rows = discoveryFixture().rows.filter(row => ids.includes(row.assetId));
    return new Response(JSON.stringify(response));
  });
  const view = await readDiscoveryView(ids, fetcher);
  expect(view.detail?.rows).toHaveLength(4);
  expect(fetcher).toHaveBeenCalledTimes(2);
  fetcher.mockClear();
  expect((await readDiscoveryView([], fetcher)).detail).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
  await expect(readDiscoveryView([...ids, "fifth"], fetcher)).rejects.toThrow("最大4件");
});

test("generation race retries the entire view once; a second race preserves saved evidence", async () => {
  const pin = comparisonPin(discoveryFixture().rows[0])!;
  const frozen = structuredClone(pin);
  let summaries = 0;
  const fetcher = vi.fn(async input => {
    if (String(input).endsWith("discovery-summary")) return new Response(JSON.stringify(summary(`g${++summaries}`)));
    return summaries === 1 ? new Response('{"error":"discovery_generation_changed"}', { status: 409 })
      : new Response(JSON.stringify(detail("g2")));
  });
  const view = await readDiscoveryView(["asset:BTC"], fetcher);
  expect(view.summary.generationId).toBe("g2"); expect(view.detail?.generationId).toBe("g2");
  expect(fetcher).toHaveBeenCalledTimes(4);
  const races = vi.fn(async input => String(input).endsWith("discovery-summary")
    ? new Response(JSON.stringify(summary("g"))) : new Response("{}", { status: 409 }));
  await expect(readDiscoveryView(["asset:BTC"], races)).rejects.toBeInstanceOf(DiscoveryGenerationChanged);
  expect(races).toHaveBeenCalledTimes(4);
  expect(pin).toEqual(frozen);
});
