import { describe, expect, it } from "vitest";
import { resolveAssetLogo } from "./asset-logo";
import bindings from "./asset-logo-bindings.json";

const btc = bindings.bindings.filter((row) => row.assetId === "crypto:BTC");
const originals = btc.map((row) => ({ instrumentId: row.instrumentId, versionId: row.versionId }));

describe("reviewed display asset identity", () => {
  it("uses the same local logo for reviewed originals across venues and reference views", () => {
    const reference = resolveAssetLogo({ assetId: "crypto:BTC", originals });
    expect(reference?.path).toMatch(/^\/asset-logos\//);
    expect(btc).toHaveLength(3);
    for (const original of btc) {
      expect(resolveAssetLogo({ instrumentId: original.instrumentId, instrumentVersionId: original.versionId })).toEqual(reference);
    }
  });

  it("falls back for a changed, absent or invalid original version", () => {
    const original = btc[0];
    for (const version of [original.versionId + 900000, 0, -1, NaN, Infinity, 1.5]) {
      expect(resolveAssetLogo({ instrumentId: original.instrumentId, instrumentVersionId: version })).toBeNull();
    }
    expect(resolveAssetLogo({ instrumentId: original.instrumentId })).toBeNull();
  });

  it("does not infer an image from an asset label or a similarly named contract", () => {
    expect(resolveAssetLogo({ assetId: "crypto:BTC" })).toBeNull();
    expect(resolveAssetLogo({ assetId: "crypto:BTC", originals: [{ instrumentId: "aster:FAKEBTCUSDT", versionId: btc[0].versionId }] })).toBeNull();
    expect(resolveAssetLogo({ instrumentId: "aster:AIUSDT", instrumentVersionId: 2316 })).toBeNull();
    expect(resolveAssetLogo({ instrumentId: "aster:1000BTCUSDT", instrumentVersionId: btc[0].versionId })).toBeNull();
  });

  it("rejects conflicting or newly unreviewed reference originals", () => {
    expect(resolveAssetLogo({ assetId: "crypto:XMR", originals })).toBeNull();
    expect(resolveAssetLogo({ assetId: "crypto:BTC", originals: [...originals, { instrumentId: "unknown:BTC", versionId: 1 }] })).toBeNull();
    expect(resolveAssetLogo({ assetId: "crypto:XMR", instrumentId: btc[0].instrumentId, instrumentVersionId: btc[0].versionId })).toBeNull();
    expect(resolveAssetLogo({ assetId: "crypto:BTC", instrumentId: btc[0].instrumentId, instrumentVersionId: btc[0].versionId, originals })).toBeNull();
  });

  it("keeps underlying identity independent of quantity and reference chart qualification", () => {
    const reviewed = originals.map((original) => ({ ...original, multiplier: null }));
    const identity = { assetId: "crypto:BTC", originals: reviewed, reference: null, widget: { status: "review" } };
    expect(resolveAssetLogo(identity)?.assetId).toBe("crypto:BTC");
  });
});
