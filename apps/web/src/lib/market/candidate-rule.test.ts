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
      "74h候補条件の詳細を取得できません。snapshot更新後に再確認してください。"
    );
    expect(formatCandidateRule74h(undefined)).toBe(
      "74h候補条件の詳細を取得できません。snapshot更新後に再確認してください。"
    );
  });
});
