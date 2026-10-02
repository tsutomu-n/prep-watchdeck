import { createHash } from "node:crypto";
import { lstatSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const manifestPath = resolve(root, "apps/web/src/lib/assets/asset-logos.json");
const outputPath = resolve(root, "apps/web/src/lib/assets/asset-logo-bindings.json");
const mapPath = resolve(root, "apps/ranking-core/data/initial-map.json");
const evidencePath = resolve(root, "apps/ranking-core/data/qualification-evidence.json");
const check = process.argv.slice(2).includes("--check");
if (process.argv.slice(2).some((arg) => arg !== "--check")) throw new Error("Only --check is supported");

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const mapBytes = readFileSync(mapPath);
const map = JSON.parse(mapBytes.toString("utf8"));
const evidence = JSON.parse(readFileSync(evidencePath, "utf8"));
requireValue(manifest.schemaVersion === 1 && Array.isArray(manifest.logos), "Invalid logo manifest");
requireValue(evidence.mapVersion === map.version, "Adopted map/evidence version mismatch");
const adoptedIds = new Set();
const bindings = [];
for (const logo of manifest.logos) {
  requireValue(typeof logo.assetId === "string" && !adoptedIds.has(logo.assetId), "Duplicate/invalid asset identity");
  adoptedIds.add(logo.assetId);
  requireValue(/^\/asset-logos\/[a-z0-9][a-z0-9.-]*\.(png|svg|webp)$/.test(logo.path), "Image must be a local static file");
  requireValue(/^[a-f0-9]{64}$/.test(logo.sha256), "Image SHA256 required");
  requireValue(Array.isArray(logo.identityEvidence) && logo.identityEvidence.length > 0, "Reviewed identity evidence required");
  requireValue(logo.usage?.redistribution === "permitted" && logo.usage.licenseUrl && logo.usage.termsUrl, "Reviewed redistribution terms required");
  const imagePath = resolve(root, "apps/web/static", logo.path.slice(1));
  const info = lstatSync(imagePath);
  requireValue(info.isFile() && !info.isSymbolicLink() && info.size > 0 && info.size <= 512 * 1024, "Unsafe/oversized static image");
  const bytes = readFileSync(imagePath);
  requireValue(createHash("sha256").update(bytes).digest("hex") === logo.sha256, "Image SHA256 mismatch");
  if (logo.path.endsWith(".png")) {
    requireValue(bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])), "Invalid PNG header");
  } else if (logo.path.endsWith(".svg")) {
    const svg = bytes.toString("utf8");
    requireValue(svg.includes("<svg") && !/<(?:script|foreignObject|image|iframe|style)\b|\bon[a-z]+\s*=|\b(?:href|src)\s*=|url\s*\(|<!DOCTYPE|<!ENTITY/i.test(svg), "SVG must contain only self-contained static vector content");
  } else {
    requireValue(bytes.subarray(0, 4).toString() === "RIFF" && bytes.subarray(8, 12).toString() === "WEBP", "Invalid WebP header");
  }
  const rows = map.rows.filter((row) => row.id === logo.assetId);
  requireValue(rows.length === 1 && rows[0].originals.length > 0, "Logo must bind one adopted original asset");
  for (const original of rows[0].originals) {
    requireValue(typeof original.instrumentId === "string" && original.instrumentId.startsWith(original.venue + ":") && Number.isSafeInteger(original.versionId) && original.versionId > 0, "Invalid adopted original identity");
    bindings.push({ instrumentId: original.instrumentId, versionId: original.versionId, assetId: logo.assetId });
  }
}
bindings.sort((a, b) => a.instrumentId.localeCompare(b.instrumentId));
requireValue(new Set(bindings.map((row) => row.instrumentId)).size === bindings.length, "Conflicting original asset bindings");
const result = JSON.stringify({ schemaVersion: 1, mapVersion: map.version, sourceMapSha256: createHash("sha256").update(mapBytes).digest("hex"), bindings }, null, 2) + "\n";
if (check) {
  requireValue(readFileSync(outputPath, "utf8") === result, "Logo bindings differ; run bun scripts/assets/generate-logo-bindings.mjs");
} else {
  writeFileSync(outputPath, result);
}
console.log(`logo bindings: ${check ? "OK" : "generated"} (${manifest.logos.length} reviewed assets, ${bindings.length} exact originals)`);
