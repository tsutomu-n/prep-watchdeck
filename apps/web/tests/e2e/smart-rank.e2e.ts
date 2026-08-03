import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const scannerCoreDir = resolve(process.cwd(), "../scanner-core");
const e2ePaths = resolveWebTestStatePaths("e2e");

function generateSnapshot(fixtureSet: string) {
  execFileSync(
    "uv",
    [
      "run",
      "watchdeck",
      "scan",
      "--source",
      "fixture",
      "--fixture-set",
      fixtureSet,
      "--template",
      "balanced"
    ],
    {
      cwd: scannerCoreDir,
      env: {
        ...process.env,
        PREP_WATCHDECK_STATE_DIR: e2ePaths.runtimeRoot
      },
      stdio: "pipe"
    }
  );
}

test("Raw Sort controls feed manual Smart Rank without persistence", async ({ page }) => {
  generateSnapshot("basic");
  await page.goto("/");

  const watchlist = page.getByRole("region", { name: "精密監視リスト" });
  const firstSymbol = watchlist.locator(".market-row .symbol").first();
  await expect(watchlist.getByText("Raw Sort: 15m 価格変化 大きい順")).toBeVisible();
  await expect(firstSymbol).toHaveText("THIN");

  await watchlist.getByText("詳細な並び替え").click();
  await watchlist.getByLabel("Raw Sortキー").selectOption("attentionScore");
  await expect(watchlist.getByText("Raw Sort: 15m 注目度 大きい順")).toBeVisible();
  await expect(firstSymbol).toHaveText("ALT");

  await watchlist.getByLabel("Raw Sortキー").selectOption("changePct");

  await watchlist.getByLabel("Raw Sort順序").selectOption("asc");
  await expect(watchlist.getByText("Raw Sort: 15m 価格変化 小さい順")).toBeVisible();
  await expect(firstSymbol).toHaveText("DUMP");

  await page
    .getByRole("region", { name: "15m ランキング" })
    .getByRole("button", { name: "74h", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 74h 価格変化 小さい順")).toBeVisible();
  await expect(watchlist.getByText("74h: 独自ルール用。72hではない。")).toBeVisible();

  const smartRank = page.getByRole("region", { name: "Smart Rank" });
  await expect(smartRank.getByText("未実行。Raw Sortで絞った後、必要な時だけ押してください。")).toBeVisible();
  await expect(smartRank.getByText(/監視優先度とデータ品質で並べ直す補助表示/)).toBeVisible();

  await smartRank.getByLabel("Smart Rank対象上限").fill("2");
  await smartRank.getByRole("button", { name: "この上位をSmart Rank" }).click();

  await expect(smartRank.getByText("対象 2 / 表示 5")).toBeVisible();
  await expect(smartRank.locator(".smart-rank-list li")).toHaveCount(2);
  await expect(smartRank.getByText("監視優先度").first()).toBeVisible();
  await expect(smartRank.locator(".smart-rank-list a").first()).toHaveAttribute("href", /\?tf=74h$/);
  await expect(smartRank.getByRole("button", { name: /\d+s/ })).toBeDisabled();
});
