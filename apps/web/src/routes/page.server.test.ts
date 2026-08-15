import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

const source = readFileSync(new URL("./+page.server.ts", import.meta.url), "utf8");

describe("Perp Universe server load", () => {
  test("loads only the schema-validated market artifact bundle", () => {
    expect(source).toContain('from "$lib/server/market-artifact-repository"');
    expect(source).toContain("createMarketArtifactRepository().latest()");
    expect(source.match(/^import /gm)).toHaveLength(1);
  });
});
