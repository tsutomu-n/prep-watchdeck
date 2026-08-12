import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
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

test("Raw Sort controls feed manual corrected ranking without persistence", async ({ page }) => {
  generateSnapshot("basic");
  const snapshot = JSON.parse(readFileSync(e2ePaths.snapshotPath, "utf-8")) as {
    rows: Array<{ symbol: string; dataQuality: string }>;
  };
  const delayed = snapshot.rows.find((row) => row.symbol === "DUMPUSDT");
  if (!delayed) throw new Error("DUMPUSDT fixture row not found");
  delayed.dataQuality = "STALE";
  writeFileSync(e2ePaths.snapshotPath, `${JSON.stringify(snapshot, null, 2)}\n`, "utf-8");
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

  await watchlist
    .getByRole("group", { name: "時間軸ショートカット" })
    .getByRole("button", { name: "24h", exact: true })
    .click();
  await expect(watchlist.getByText("Raw Sort: 24h 価格変化 小さい順")).toBeVisible();

  const smartRank = page.getByRole("region", { name: "補正順位" });
  await expect(smartRank.getByText("未実行。Raw Sortで絞った後、必要な時だけ押してください。")).toBeVisible();
  await expect(smartRank.getByText(/監視優先度とデータ品質で並べ直す補助表示/)).toBeVisible();

  await smartRank.getByLabel("補正順位対象上限").fill("5");
  await smartRank.getByRole("button", { name: "上位を補正" }).click();
  await expect(smartRank.getByText(/Raw #\d+ → 補正 #1/)).toBeVisible();

  await expect(smartRank.getByText("対象 5 / 表示 5")).toBeVisible();
  await expect(smartRank.locator(".smart-rank-list li")).toHaveCount(5);
  await expect(smartRank.getByText("監視優先度").first()).toBeVisible();
  await expect(smartRank.getByText("更新遅延による補正 -12", { exact: true })).toBeVisible();
  await expect(smartRank.locator(".smart-rank-list a").first()).toHaveAttribute("href", /\?tf=24h$/);
  await expect(smartRank.getByRole("button", { name: /\d+s/ })).toBeDisabled();
});
