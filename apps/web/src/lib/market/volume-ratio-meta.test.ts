import { describe, expect, it } from "vitest";
import {
  formatVolumeRatioBaseline,
  formatVolumeRatioHelp,
  parseVolumeRatio15mMeta
} from "./volume-ratio-meta";

const validMeta = {
  windowMinutes: 15,
  sampleStepMinutes: 5,
  baselineSampleCount: 288,
  approxBaselineSpanMinutes: 1440,
  statistic: "median",
  floorUsdt: 1000
};

describe("15m volume ratio metadata", () => {
  it("parses the closed metadata shape and describes its real rolling samples", () => {
    expect(parseVolumeRatio15mMeta(validMeta)).toEqual(validMeta);
    expect(formatVolumeRatioBaseline(validMeta)).toBe("直近約24h中央値比");
    expect(formatVolumeRatioHelp(validMeta)).toBe(
      "現在15分のUSDT売買代金 ÷ 過去288サンプル（5分刻み、約24h）のrolling 15分売買代金中央値（基準下限 1,000 USDT）"
    );
  });

  it("formats alternate active configuration without assuming 24 hours", () => {
    const meta = {
      ...validMeta,
      baselineSampleCount: 96,
      approxBaselineSpanMinutes: 480,
      floorUsdt: 2500
    };

    expect(formatVolumeRatioBaseline(meta)).toBe("直近約8h中央値比");
    expect(formatVolumeRatioHelp(meta)).toContain("過去96サンプル（5分刻み、約8h）");
    expect(formatVolumeRatioHelp(meta)).toContain("基準下限 2,500 USDT");
  });

  it.each([
    undefined,
    {},
    { ...validMeta, baselineSampleCount: Number.NaN },
    { ...validMeta, baselineSampleCount: -1 },
    { ...validMeta, approxBaselineSpanMinutes: 1435 },
    { ...validMeta, floorUsdt: 0 },
    { ...validMeta, statistic: "average" }
  ])("falls back without guessing periods for invalid metadata", (value) => {
    expect(parseVolumeRatio15mMeta(value)).toBeNull();
    expect(formatVolumeRatioBaseline(value)).toBe("基準期間を取得できません");
    expect(formatVolumeRatioHelp(value)).toBe(
      "現在15分のUSDT売買代金をrolling 15分売買代金の基準中央値と比較します。基準期間の詳細は取得できません。"
    );
  });
});
