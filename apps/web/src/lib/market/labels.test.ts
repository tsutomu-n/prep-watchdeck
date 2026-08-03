import { describe, expect, it } from "vitest";
import {
  categoryLabel,
  changeTone,
  codeLabel,
  dataQualityClass,
  dataQualityLabel,
  dataSourceLabel,
  rowExclusionLabels,
  rowQualityClass,
  snapshotStatusLabel,
  templateLabel
} from "./labels";

describe("market label helpers", () => {
  it("maps known domain codes to stable Japanese labels", () => {
    expect(categoryLabel("ALL")).toBe("すべて");
    expect(categoryLabel("WATCH")).toBe("注視");
    expect(categoryLabel("NO_TRADE")).toBe("監視除外候補");
    expect(dataQualityLabel("PARTIAL")).toBe("一部不足");
    expect(snapshotStatusLabel("STALE")).toBe("古い");
    expect(dataSourceLabel("fixture")).toBe("検証データ");
    expect(templateLabel("thin-spike")).toBe("薄商い急変");
    expect(codeLabel("VOLUME_CONFIRMED_UP")).toBe("出来高確認済み上昇");
    expect(codeLabel("DATA_GAP_REPAIRABLE")).toBe("Bitget補修対象");
    expect(codeLabel("DATA_HISTORY_SHORT")).toBe("履歴不足");
    expect(codeLabel("DATA_ZERO_VOLUME")).toBe("ゼロ出来高注意");
  });

  it("keeps unknown codes visible unless a fallback is explicitly provided", () => {
    expect(codeLabel("NEW_CODE")).toBe("NEW_CODE");
    expect(codeLabel("NEW_CODE", "未分類")).toBe("未分類");
    expect(categoryLabel("UNKNOWN")).toBe("未分類");
  });

  it("splits value tone, data-quality class, and row-quality class", () => {
    expect(changeTone(1)).toBe("good");
    expect(changeTone(-1)).toBe("risk");
    expect(changeTone(null)).toBe("neutral");
    expect(dataQualityClass("OK")).toBe("good");
    expect(dataQualityClass("STALE")).toBe("risk");
    expect(rowQualityClass({ category: "NO_TRADE", dataQuality: "OK" })).toBe("risk");
    expect(rowQualityClass({ category: "WATCH", dataQuality: "OK" })).toBe("ok");
  });

  it("builds selected-row exclusion labels without duplicates", () => {
    expect(
      rowExclusionLabels({
        category: "NO_TRADE",
        label: "THIN_SPIKE",
        dataQuality: "MISSING",
        riskTagCodes: ["THIN_SPIKE", "DATA_MISSING", "THIN_SPIKE"]
      })
    ).toEqual(["監視除外候補", "薄商い急変", "欠損", "データ欠損"]);

    expect(
      rowExclusionLabels({
        category: "WATCH",
        label: "VOLUME_CONFIRMED_UP",
        dataQuality: "OK",
        riskTagCodes: []
      })
    ).toEqual([]);
  });
});
