import { describe, expect, it, vi } from "vitest";
import { rankingFixture } from "$lib/market/ranking-test-fixture";
import { rankingQuery } from "$lib/market/ranking";
import { normalizeRankingQuery, RankingReader } from "./ranking";

describe("independent ranking read path", () => {
  it("only contacts the fixed loopback ranking API and requires no Core artifacts", async () => {
    const response = rankingFixture();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(response));
    const reader = new RankingReader(fetcher, { PREP_WATCHDECK_RANKING_PORT: "18769" });
    expect((await reader.read(rankingQuery("15m", "00:00", "gainers", 0))).generationId).toBe(response.generationId);
    expect(fetcher.mock.calls[0][0]).toMatch(/^http:\/\/127\.0\.0\.1:18769\/rankings\?/);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects incomplete or mismatched generations", async () => {
    const response = rankingFixture();
    for (const invalid of [
      { ...response, schemaVersion: "other" },
      { ...response, schemaVersion: "ranking-v1" },
      { ...response, period: "1h" },
      { ...response, rows: [response.rows[0], response.rows[0]] },
      { ...response, cutoff: response.cutoff + 1 },
      { ...response, rows: [{ ...response.rows[0], returnPct: "not-a-number" }] }
    ]) {
      const reader = new RankingReader(vi.fn<typeof fetch>().mockResolvedValue(Response.json(invalid)));
      await expect(reader.read(rankingQuery("15m", "00:00", "gainers", 0))).rejects.toThrow();
    }
  });

  it("accepts qualified reference metrics while quantity and Widget reviews remain open", async () => {
    const response = rankingFixture();
    response.rows[0].originals[0].multiplier = null;
    response.rows[0].widget = { status: "review", symbol: null, referenceKey: null,
      reason: "widget_not_reviewed", evidence: [] };
    const reader = new RankingReader(vi.fn<typeof fetch>().mockResolvedValue(Response.json(response)));
    const actual = await reader.read(rankingQuery("15m", "00:00", "gainers", 0));
    expect(actual.rows[0].rank).toBe(1);
    expect(actual.rows[0].originals[0].multiplier).toBeNull();
    expect(actual.rows[0].widget.status).toBe("review");
  });

  it("retains the source time for stale snapshots instead of hiding them", async () => {
    const response = rankingFixture(undefined, Date.now() - 600_000 - (Date.now() % 60_000));
    response.stale = true; response.status = "stale";
    const reader = new RankingReader(vi.fn<typeof fetch>().mockResolvedValue(Response.json(response)));
    expect((await reader.read(rankingQuery("15m", "00:00", "gainers", 0))).generatedAt).toBe(response.generatedAt);
  });

  it("rejects URL-shaped ports, DB ports, duplicates and external symbol input", async () => {
    const fetcher = vi.fn<typeof fetch>();
    for (const port of ["5432", "55432", "https://example.com", "65536"]) {
      await expect(new RankingReader(fetcher, { PREP_WATCHDECK_RANKING_PORT: port }).read(
        rankingQuery("15m", "00:00", "gainers", 0))).rejects.toThrow();
    }
    for (const query of ["period=15m&period=1h", "symbol=NASDAQ:AAPL", "dailyReferenceJst=24:00"]) {
      expect(() => normalizeRankingQuery(new URLSearchParams(query))).toThrow();
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
});
