import manifest from "./asset-logos.json";
import bindings from "./asset-logo-bindings.json";

export type OriginalLogoIdentity = { instrumentId: string; versionId: number };
export type AssetLogoIdentity = {
  assetId?: string | null;
  originals?: readonly OriginalLogoIdentity[];
  instrumentId?: string | null;
  instrumentVersionId?: number | null;
};
export type AssetLogo = { assetId: string; name: string; path: string };

const localImage = /^\/asset-logos\/[a-z0-9][a-z0-9.-]*\.(?:png|svg|webp)$/;
const logos = new Map<string, AssetLogo>();
for (const entry of manifest.logos) {
  if (localImage.test(entry.path)) {
    logos.set(entry.assetId, { assetId: entry.assetId, name: entry.name, path: entry.path });
  }
}
const originalAssets = new Map(bindings.bindings.map((entry) => [
  `${entry.instrumentId}@${entry.versionId}`, entry.assetId
]));

function originalAsset(instrumentId: string, versionId: number): string | undefined {
  if (!Number.isSafeInteger(versionId) || versionId < 1) return undefined;
  return originalAssets.get(`${instrumentId}@${versionId}`);
}

/** Display-only identity: symbols, prices, multipliers and Widget qualification are not inputs. */
export function resolveAssetLogo(identity: AssetLogoIdentity): AssetLogo | null {
  if (identity.instrumentId != null || identity.instrumentVersionId != null) {
    if (identity.originals !== undefined) return null;
    if (identity.instrumentId == null || identity.instrumentVersionId == null) return null;
    const assetId = originalAsset(identity.instrumentId, identity.instrumentVersionId);
    if (!assetId || (identity.assetId != null && identity.assetId !== assetId)) return null;
    return logos.get(assetId) ?? null;
  }
  if (!identity.assetId || !identity.originals?.length) return null;
  // A newer, missing or conflicting original definition needs a new display identity review.
  if (!identity.originals.every((entry) =>
    originalAsset(entry.instrumentId, entry.versionId) === identity.assetId)) return null;
  return logos.get(identity.assetId) ?? null;
}

export function logoPlaceholder(symbol: string): string {
  return symbol.match(/[A-Za-z0-9]/g)?.slice(0, 2).join("").toUpperCase() || "?";
}
