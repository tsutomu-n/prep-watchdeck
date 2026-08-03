import { expect, test } from "@playwright/test";

test("symbol page keeps the monitoring evidence in a monitoring-only rail", async ({ page }) => {
  await page.goto("/symbols/ALTUSDT?tf=15m");

  const monitoringRail = page.locator("#symbol-monitoring");
  await expect(monitoringRail).toBeVisible();
  await expect(monitoringRail).toHaveAttribute("aria-label", "監視材料");
  await expect(page.getByRole("complementary", { name: "監視材料" })).toHaveCount(1);
  await expect(monitoringRail.getByRole("heading", { name: "監視材料", exact: true })).toBeVisible();

  await expect(monitoringRail.locator("dt").filter({ hasText: /^分類$/ }).locator("..")).toContainText(
    "注視"
  );
  await expect(monitoringRail.locator("dt").filter({ hasText: /^ラベル$/ }).locator("..")).toContainText(
    "出来高確認済み上昇"
  );
  await expect(monitoringRail.locator("dt").filter({ hasText: /^品質$/ }).locator("..")).toContainText(
    "正常"
  );
  await expect(monitoringRail.locator("dt").filter({ hasText: /^時間軸$/ }).locator("..")).toContainText(
    "15m"
  );

  await expect(
    monitoringRail.getByRole("heading", { name: "ランキング位置", exact: true })
  ).toBeVisible();
  await expect(monitoringRail.locator(".rank-context dt")).toHaveText([
    "上昇順",
    "下落順",
    "売買代金",
    "出来高倍率"
  ]);
  await expect(monitoringRail.getByRole("heading", { name: "即時シグナル", exact: true })).toBeVisible();
  await expect(monitoringRail.getByText("5分/1時間一致", { exact: true })).toBeVisible();
  await expect(monitoringRail.getByText("出来高増", { exact: true })).toBeVisible();

  await page.goto("/symbols/DUMPUSDT?tf=15m");
  await expect(page.locator("#symbol-monitoring").getByText("急落", { exact: true })).toBeVisible();
});

test("symbol page keeps Past Note and monitoring navigation usable on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  const reason = `監視専用 E2E ${Date.now()}`;
  const note = "出来高と急変の再確認";
  let submittedBody: unknown;

  await page.route("**/api/past-notes", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    submittedBody = route.request().postDataJSON();
    await route.fulfill({
      json: {
        notes: [
          {
            symbol: "ALTUSDT",
            reason,
            note,
            observedAt: "2026-08-02T12:00:00.000Z",
            expiresAt: "2026-10-01T12:00:00.000Z"
          }
        ]
      }
    });
  });

  await page.goto("/symbols/ALTUSDT?tf=15m");
  const pastNotes = page.locator("#symbol-past-notes");
  await pastNotes.getByLabel("理由", { exact: true }).fill(reason);
  await pastNotes.getByLabel("メモ", { exact: true }).fill(note);
  await pastNotes.getByRole("button", { name: "銘柄注記を保存" }).click();

  expect(submittedBody).toEqual({ symbol: "ALTUSDT", reason, note });
  await expect(pastNotes.getByText(`銘柄注記: ${reason} - ${note}`, { exact: true })).toBeVisible();

  const sectionNavigation = page.getByRole("navigation", { name: "個別分析内を移動" });
  await expect(sectionNavigation.getByRole("link", { name: "監視材料", exact: true })).toHaveAttribute(
    "href",
    "#symbol-monitoring"
  );
  await expect(sectionNavigation.getByRole("link", { name: "銘柄注記", exact: true })).toHaveAttribute(
    "href",
    "#symbol-past-notes"
  );
});
