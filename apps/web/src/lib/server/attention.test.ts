import { describe, expect, it, vi } from "vitest";
import { attentionFixture } from "$lib/attention/attention-test-fixture";
import { AttentionReader } from "./attention";

describe("Attention validated loopback read", () => {
  it("uses one fixed bounded no-store read and preserves distinct source times", async () => {
    const fixture = attentionFixture();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json(fixture));
    const result = await new AttentionReader(fetcher, { PREP_WATCHDECK_ATTENTION_PORT: "18770" }).read();
    expect(result.inputs.rankingCutoff).toBe(fixture.inputs.rankingCutoff);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toBe("http://127.0.0.1:18770/attention");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ redirect: "error", cache: "no-store" });
    expect(fetcher.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });
  it("rejects invalid ports, future/mixed generations, duplicate rows and unavailable-score imputation", async () => {
    const fetcher = vi.fn<typeof fetch>();
    for (const port of ["8769", "5432", "55432", "https://example.org", "65536"])
      await expect(new AttentionReader(fetcher, { PREP_WATCHDECK_ATTENTION_PORT: port }).read()).rejects.toThrow();
    expect(fetcher).not.toHaveBeenCalled();
    const fixture = attentionFixture();
    const imputed = structuredClone(fixture); imputed.rows[1].components.confluence.score = 0;
    for (const payload of [{ ...fixture, schemaVersion: "v0" }, { ...fixture, decisionAt: Date.now() + 60_000 },
      { ...fixture, rows: [fixture.rows[0], fixture.rows[0]] }, imputed]) {
      fetcher.mockResolvedValue(Response.json(payload));
      await expect(new AttentionReader(fetcher).read()).rejects.toThrow();
    }
  });
  it("retains stopped generation timestamps and rejects oversize/unavailable responses", async () => {
    const fixture = attentionFixture(Date.now() - 600_000);
    const result = await new AttentionReader(vi.fn<typeof fetch>().mockResolvedValue(Response.json(fixture))).read();
    expect(result.status).toBe("stale"); expect(result.decisionAt).toBe(fixture.decisionAt);
    for (const response of [new Response("unavailable", { status: 503 }), new Response("x".repeat(8 * 1024 * 1024 + 1))])
      await expect(new AttentionReader(vi.fn<typeof fetch>().mockResolvedValue(response)).read()).rejects.toThrow();
  });
});
