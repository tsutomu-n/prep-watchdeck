import { describe, expect, it } from "vitest";
import { formatCandidateRule74h } from "./candidate-rule";

describe("candidate rule summary", () => {
  it("renders validated thresholds and candidate counts", () => {
    expect(
      formatCandidateRule74h({
        operator: "AND",
        priceAbsPct: 4,
        turnoverIncreasePct: 15,
        turnoverMode: "current_24h_vs_74h_ago_24h",
        eligible: 1,
        notMatched: 0,
        unknown: 3
      })
    ).toBe(
      "74h条件: 価格±4%以上 かつ 24h売買代金+15%以上（合致1 / 未一致0 / 判定不能3）"
    );
  });

  it("falls back without guessing numbers when the summary is malformed", () => {
    expect(formatCandidateRule74h({ operator: "AND", priceAbsPct: "4" })).toBe(
      "74h価格条件かつ74h売買代金条件。履歴不足は候補に含めません。"
    );
  });
});
