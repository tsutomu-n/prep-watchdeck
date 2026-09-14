import { describe, expect, test } from "bun:test";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const repoRoot = resolve(import.meta.dirname, "../..");

function read(path) {
  return readFileSync(resolve(repoRoot, path), "utf8");
}

const productBoundary = read("docs/current/product-boundary.md");
const decision0012 = read("docs/decisions/0012-product-evolution-boundary.md");
const agents = read("AGENTS.md");
const design = read("DESIGN.md");
const operations = read("docs/current/operations.md");
const p0Baseline = read("docs/current/watchdeck-v1-scope.md");
const decision0007 = read("docs/decisions/0007-monitoring-only-product-boundary.md");
const decision0011 = read("docs/decisions/0011-perp-universe-replacement.md");

describe("extensible product boundary", () => {
  test("allows the approved discretionary-analysis expansion surface", () => {
    for (const expected of [
      "Ranking",
      "Stocks",
      "paid market data",
      "ML",
      "backtest",
      "Decision Memo",
      "Trade Journal"
    ]) {
      expect(productBoundary).toContain(expected);
    }
  });

  test("keeps automatic execution behind a separate explicit decision", () => {
    expect(productBoundary).toContain("自動注文、資金移動、無人execution");
    expect(productBoundary).toContain("別Decision");
    expect(decision0012).toContain("自動注文、資金移動、無人execution");
  });

  test("does not treat current implementation constants as permanent product limits", () => {
    expect(productBoundary).toContain("永久制約ではない");
    expect(decision0012).toContain("永久の製品契約ではない");
    expect(productBoundary).toContain("timeframe");
    expect(productBoundary).toContain("artifact");
  });

  test("allows design evolution while retaining UX and accessibility principles", () => {
    expect(design).toContain("永久禁止しない");
    expect(design).toContain("gradient");
    expect(design).toContain("shadow");
    expect(design).toContain("animation");
    expect(design).toContain("accessibility");
  });

  test("allows reviewed credentialed read-only sources", () => {
    expect(productBoundary).toContain("credential付きread-only API");
    expect(operations).toContain(
      "paid APIやcredential付きread-only APIであること自体は製品全体の停止条件ではない"
    );
  });

  test("agents use the new product boundary before legacy P0 decisions", () => {
    expect(agents).toContain("docs/current/product-boundary.md");
    expect(agents).toContain("0012-product-evolution-boundary.md");
    expect(agents.indexOf("docs/current/product-boundary.md")).toBeLessThan(
      agents.indexOf("docs/current/architecture.md")
    );
  });

  test("P0 freeze is recorded as completed history, not an active ban", () => {
    expect(p0Baseline).toContain("P0後の製品拡張を禁止する文書ではない");
    expect(p0Baseline).not.toContain("P0完了前後に次を追加しない");
  });

  test("Decision 0007 no longer keeps the monitoring-only boundary active", () => {
    expect(decision0007).toContain("製品境界はsuperseded");
    expect(decision0007).toContain("Decision 0012");
    expect(decision0007).toContain("旧feature名をCIで禁止しない");
    expect(decision0007).not.toContain("市場監視専用、Past Note、state、退役APIの境界は引き続き有効");
  });

  test("Decision 0011 delegates future product scope to Decision 0012", () => {
    expect(decision0011).toContain("Decision 0012");
    expect(decision0011).toContain("製品境界は一部superseded");
  });

  test("retired monitoring-only vocabulary ban is not part of the active gate", () => {
    expect(
      existsSync(resolve(repoRoot, "scripts/maintenance/monitoring-only-boundary.test.mjs"))
    ).toBe(false);
  });
});
