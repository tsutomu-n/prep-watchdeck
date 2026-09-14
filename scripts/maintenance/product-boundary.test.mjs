import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const repoRoot = resolve(import.meta.dirname, "../..");
const read = (path) => readFileSync(resolve(repoRoot, path), "utf8");

const productBoundary = read("docs/current/product-boundary.md");
const decision0012 = read("docs/decisions/0012-product-evolution-boundary.md");
const agents = read("AGENTS.md");
const design = read("DESIGN.md");
const operations = read("docs/current/operations.md");
const p0Baseline = read("docs/current/watchdeck-v1-scope.md");
const decision0007 = read("docs/decisions/0007-monitoring-only-product-boundary.md");
const decision0011 = read("docs/decisions/0011-perp-universe-replacement.md");


describe("extensible product boundary", () => {
  test("keeps approved analysis and design evolution inside the product boundary", () => {
    for (const expected of ["Ranking", "Stocks", "paid market data", "ML", "backtest", "Trade Journal"]) {
      expect(productBoundary).toContain(expected);
    }
    expect(productBoundary).toContain("永久制約ではない");
    expect(decision0012).toContain("永久の製品契約ではない");
    expect(design).toContain("永久禁止しない");
    expect(operations).toContain(
      "paid APIやcredential付きread-only APIであること自体は製品全体の停止条件ではない"
    );
  });

  test("keeps automatic execution behind a separate explicit safety decision", () => {
    expect(productBoundary).toContain("自動注文、資金移動、無人execution");
    expect(productBoundary).toContain("別Decision");
    expect(decision0012).toContain("自動注文、資金移動、無人execution");
  });

  test("delegates legacy P0 boundaries to the current product contract", () => {
    expect(agents.indexOf("docs/current/product-boundary.md")).toBeLessThan(
      agents.indexOf("docs/current/architecture.md")
    );
    expect(p0Baseline).toContain("P0後の製品拡張を禁止する文書ではない");
    expect(decision0007).toContain("製品境界はsuperseded");
    expect(decision0007).toContain("Decision 0012");
    expect(decision0011).toContain("製品境界は一部superseded");
    expect(decision0011).toContain("Decision 0012");
    expect(
      existsSync(resolve(repoRoot, "scripts/maintenance/monitoring-only-boundary.test.mjs"))
    ).toBe(false);
  });
});
