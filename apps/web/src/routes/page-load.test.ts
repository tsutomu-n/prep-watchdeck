import { beforeEach, describe, expect, test, vi } from "vitest";
import { load } from "./+page.server";
import { load as loadLegacyRanking } from "./rankings/+page.server";

const { latest, createRepository } = vi.hoisted(() => {
  const latest = vi.fn();
  return { latest, createRepository: vi.fn(() => ({ latest })) };
});
vi.mock("$lib/server/market-artifact-repository", () => ({
  createMarketArtifactRepository: createRepository
}));

beforeEach(() => vi.clearAllMocks());

describe("Markets page artifact loading", () => {
  test.each(["/", "/?mode=reference", "/?mode=unknown", "/rankings", "/rankings?period=1h"])(
    "%s opens the reference surface without reading Native artifacts",
    async (path) => {
      const loader = path.startsWith("/rankings") ? loadLegacyRanking : load;
      expect(await loader({ url: new URL(path, "http://localhost") })).toEqual({});
      expect(createRepository).not.toHaveBeenCalled();
      expect(latest).not.toHaveBeenCalled();
    }
  );

  test("explicit Native navigation preserves the artifact bundle", async () => {
    const bundle = { universe: {}, chart: {}, selected: {}, service: {} };
    latest.mockResolvedValueOnce(bundle);
    const result = await load({ url: new URL("http://localhost/?mode=native&instrument=bitget:BTCUSDT") });
    expect(result).toEqual({ market: bundle });
    expect(latest).toHaveBeenCalledOnce();
  });

  test("Native artifact failures preserve the existing error contract", async () => {
    latest.mockRejectedValueOnce(new Error("market artifacts changed while being read"));
    expect(await load({ url: new URL("http://localhost/?mode=native") })).toEqual({
      marketError: "market artifacts changed while being read"
    });
    latest.mockRejectedValueOnce(null);
    expect(await load({ url: new URL("http://localhost/?mode=native") })).toEqual({
      marketError: "market artifacts unavailable"
    });
  });
});
