import { describe, expect, it } from "vitest";
import { pastNoteSummary } from "./past-note-view";

describe("past note view helpers", () => {
  it("uses monitoring annotation wording with and without note text", () => {
    expect(pastNoteSummary({ reason: "前回急変", note: "出来高だけ先行" })).toBe(
      "銘柄注記: 前回急変 - 出来高だけ先行"
    );
    expect(pastNoteSummary({ reason: "前回急変", note: "" })).toBe("銘柄注記: 前回急変");
  });
});
