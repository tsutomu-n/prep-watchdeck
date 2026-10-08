import { expect, it } from "vitest";
import { attentionFixture } from "./attention-test-fixture";
import { displayScore, nativeLink, referenceLink, visibleRows, isFavorite, reasonLabel } from "./attention";

it("filters and favorite overlay never rewrite market ranks or impute scores", () => {
  const response = attentionFixture();
  const favorites = new Set(["asset:ETH"]);
  const result = visibleRows(response, "movement", "", false, true, favorites);
  expect(result.map(row => row.asset)).toEqual(["ETH", "BTC"]);
  expect(result[0].components.movement.rank).toBe(2);
  expect(visibleRows(response, "confluence", "", true, false, favorites).length).toBe(1);
  expect(visibleRows(response, "movement", "eth", false, false, favorites)[0].asset).toBe("ETH");
  expect(displayScore(null)).toBe("—"); expect(displayScore(0)).toBe("0.0");
  expect(reasonLabel("incomplete_components")).toContain("4成分");
});

it("links and favorite membership require exact contract identity", () => {
  const row = attentionFixture().rows[0];
  expect(referenceLink(row)).toBe("/?mode=reference&selected=asset%3ABTC");
  expect(nativeLink(row.originals[0])).toBe("/?mode=native&instrument=bitget%3ABTCUSDT&version=1");
  expect(nativeLink({ ...row.originals[0], current: false })).toBeNull();
  expect(isFavorite(row, [{ kind: "instrument", id: "bitget:BTCUSDT", version: 2 }])).toBe(false);
  expect(isFavorite(row, [{ kind: "instrument", id: "bitget:BTCUSDT", version: 1 }])).toBe(true);
});
