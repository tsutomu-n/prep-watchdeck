import {
  expect,
  test,
  type Locator,
  type Page,
  type Route
} from "@playwright/test";

function dispatchClick(locator: Locator) {
  return locator.evaluate((element) =>
    element.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  );
}

function deferredGate() {
  let release = () => {};
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

async function clientNavigateToSymbol(page: Page, symbol: string) {
  const marker = `symbol-client-navigation-${symbol}-${Date.now()}`;
  const href = `/symbols/${encodeURIComponent(symbol)}?tf=15m`;
  await page.evaluate(
    ({ nextHref, nextMarker }) => {
      const browserWindow = window as Window & { __symbolClientNavigationMarker?: string };
      browserWindow.__symbolClientNavigationMarker = nextMarker;
      let anchor = document.querySelector<HTMLAnchorElement>("[data-e2e-symbol-navigation]");
      if (!anchor) {
        anchor = document.createElement("a");
        anchor.dataset.e2eSymbolNavigation = "true";
        anchor.style.position = "fixed";
        anchor.style.inset = "0 auto auto 0";
        anchor.style.zIndex = "9999";
        document.body.append(anchor);
      }
      anchor.href = nextHref;
      anchor.textContent = `E2E ${nextHref}`;
    },
    { nextHref: href, nextMarker: marker }
  );

  await page.locator("[data-e2e-symbol-navigation]").click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(`/symbols/${symbol}`);
  await expect.poll(() => new URL(page.url()).searchParams.get("tf")).toBe("15m");
  expect(
    await page.evaluate(
      () => (window as Window & { __symbolClientNavigationMarker?: string }).__symbolClientNavigationMarker
    )
  ).toBe(marker);
}

async function exercisePastNoteResponseAcrossSymbolNavigation(
  page: Page,
  responseMode: "success" | "failure"
) {
  const gate = deferredGate();
  const responseSettled = deferredGate();
  const submittedReason = `ALT pending ${responseMode}`;
  const submittedNote = `ALT note ${responseMode}`;
  const symbolBReason = `THIN draft ${responseMode}`;
  const symbolBNote = `THIN note ${responseMode}`;
  let postCalls = 0;
  let submittedBody: { symbol?: string; reason?: string; note?: string } | null = null;

  const routeHandler = async (route: Route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    postCalls += 1;
    submittedBody = route.request().postDataJSON() as {
      symbol?: string;
      reason?: string;
      note?: string;
    };
    try {
      await gate.wait;
      if (responseMode === "success") {
        await route.fulfill({
          json: {
            notes: [
              {
                symbol: "ALTUSDT",
                reason: submittedReason,
                note: submittedNote,
                observedAt: "2026-07-18T07:00:00.000Z",
                expiresAt: "2026-08-17T07:00:00.000Z"
              }
            ]
          }
        });
      } else {
        await route.fulfill({ status: 500, contentType: "text/plain", body: "forced E2E failure" });
      }
    } finally {
      responseSettled.release();
    }
  };

  await page.route("**/api/past-notes", routeHandler);
  try {
    await page.goto("/symbols/ALTUSDT?tf=15m");
    const symbolAPanel = page.locator("#symbol-past-notes");
    await symbolAPanel.getByLabel("理由", { exact: true }).fill(submittedReason);
    await symbolAPanel.getByLabel("メモ", { exact: true }).fill(submittedNote);
    const saveButton = symbolAPanel.locator("button[data-single-line-action]");
    await saveButton.click();
    await expect.poll(() => postCalls).toBe(1);
    expect(submittedBody).toEqual({
      symbol: "ALTUSDT",
      reason: submittedReason,
      note: submittedNote
    });
    await expect(saveButton).toBeDisabled();

    await dispatchClick(saveButton);
    await dispatchClick(saveButton);
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
    expect(postCalls).toBe(1);

    await clientNavigateToSymbol(page, "THINUSDT");
    const symbolBPanel = page.locator("#symbol-past-notes");
    const symbolBReasonInput = symbolBPanel.getByLabel("理由", { exact: true });
    const symbolBNoteInput = symbolBPanel.getByLabel("メモ", { exact: true });
    await expect(symbolBReasonInput).toHaveValue("");
    await expect(symbolBNoteInput).toHaveValue("");
    await symbolBReasonInput.fill(symbolBReason);
    await symbolBNoteInput.fill(symbolBNote);
    await expect(symbolBPanel.getByRole("button", { name: "保存中" })).toBeDisabled();

    gate.release();
    await responseSettled.wait;
    await expect(symbolBPanel.getByRole("button", { name: "銘柄注記を保存" })).toBeEnabled();
    await expect(symbolBReasonInput).toHaveValue(symbolBReason);
    await expect(symbolBNoteInput).toHaveValue(symbolBNote);
    await expect(symbolBPanel.getByRole("alert")).toHaveCount(0);
    await expect(symbolBPanel.getByRole("status")).toHaveCount(0);

    await clientNavigateToSymbol(page, "ALTUSDT");
    const returnedSymbolAPanel = page.locator("#symbol-past-notes");
    if (responseMode === "success") {
      await expect(returnedSymbolAPanel.getByRole("status")).toHaveText("銘柄注記を保存しました");
      await expect(returnedSymbolAPanel.getByRole("alert")).toHaveCount(0);
    } else {
      await expect(returnedSymbolAPanel.getByRole("alert")).toHaveText("銘柄注記の保存に失敗しました");
      await expect(returnedSymbolAPanel.getByRole("status")).toHaveCount(0);
    }
  } finally {
    gate.release();
    if (postCalls > 0) await responseSettled.wait;
    await page.unroute("**/api/past-notes", routeHandler);
  }
}

async function exercisePastNoteRoundTripToSubmittedSymbol(
  page: Page,
  editAfterReturn: boolean
) {
  const suffix = `past-note-round-trip-${editAfterReturn ? "v2" : "empty"}-${Date.now()}`;
  const submittedReason = `round trip reason V1 ${suffix}`;
  const submittedNote = `round trip note V1 ${suffix}`;
  const newerReason = `round trip reason V2 ${suffix}`;
  const newerNote = `round trip note V2 ${suffix}`;
  const gate = deferredGate();
  const settled = deferredGate();
  let postCalls = 0;
  let submittedBody: { symbol?: string; reason?: string; note?: string } | null = null;

  const routeHandler = async (route: Route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    postCalls += 1;
    submittedBody = route.request().postDataJSON() as {
      symbol?: string;
      reason?: string;
      note?: string;
    };
    try {
      await gate.wait;
      await route.fulfill({
        json: {
          notes: [
            {
              symbol: "ALTUSDT",
              reason: submittedReason,
              note: submittedNote,
              observedAt: "2026-07-18T07:00:00.000Z",
              expiresAt: "2026-08-17T07:00:00.000Z"
            }
          ]
        }
      });
    } finally {
      settled.release();
    }
  };

  await page.route("**/api/past-notes", routeHandler);
  try {
    await page.goto("/symbols/ALTUSDT?tf=15m");
    const initialPanel = page.locator("#symbol-past-notes");
    await initialPanel.getByLabel("理由", { exact: true }).fill(submittedReason);
    await initialPanel.getByLabel("メモ", { exact: true }).fill(submittedNote);
    await initialPanel.getByRole("button", { name: "銘柄注記を保存" }).click();
    await expect.poll(() => postCalls).toBe(1);
    expect(submittedBody).toEqual({
      symbol: "ALTUSDT",
      reason: submittedReason,
      note: submittedNote
    });

    await clientNavigateToSymbol(page, "THINUSDT");
    await clientNavigateToSymbol(page, "ALTUSDT");
    const returnedPanel = page.locator("#symbol-past-notes");
    const returnedReasonInput = returnedPanel.getByLabel("理由", { exact: true });
    const returnedNoteInput = returnedPanel.getByLabel("メモ", { exact: true });
    await expect(returnedReasonInput).toHaveValue("");
    await expect(returnedNoteInput).toHaveValue("");
    if (editAfterReturn) {
      await returnedReasonInput.fill(newerReason);
      await returnedNoteInput.fill(newerNote);
    }

    gate.release();
    await expect(returnedPanel.getByRole("status")).toHaveText(
      editAfterReturn
        ? "送信時点の内容を保存しました。追加の変更は未保存です"
        : "銘柄注記を保存しました"
    );
    await expect(
      returnedPanel.locator(".note-list article").filter({ hasText: submittedReason })
    ).toContainText(submittedNote);
    await expect(returnedReasonInput).toHaveValue(editAfterReturn ? newerReason : "");
    await expect(returnedNoteInput).toHaveValue(editAfterReturn ? newerNote : "");
    if (!editAfterReturn) {
      await returnedReasonInput.fill(newerReason);
      await expect(returnedPanel.getByRole("status")).toHaveCount(0);
      await expect(returnedReasonInput).toHaveValue(newerReason);
    } else {
      await returnedReasonInput.fill(`${newerReason} updated`);
      await expect(returnedPanel.getByRole("status")).toHaveText(
        "送信時点の内容を保存しました。追加の変更は未保存です"
      );
    }
  } finally {
    gate.release();
    if (postCalls > 0) await settled.wait;
    await page.unroute("**/api/past-notes", routeHandler);
  }
}

async function readBox(locator: Locator) {
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      left: box.left,
      right: box.right,
      top: box.top,
      bottom: box.bottom,
      width: box.width,
      backgroundColor: style.backgroundColor,
      borderTopWidth: style.borderTopWidth,
      borderRightWidth: style.borderRightWidth,
      borderBottomWidth: style.borderBottomWidth,
      borderLeftWidth: style.borderLeftWidth,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
      columnGap: style.columnGap,
      rowGap: style.rowGap
    };
  });
}

test("symbol support information is one flat divided workspace in workflow order", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/symbols/ALTUSDT?tf=15m");

  const symbolPage = page.locator("main.symbol-page");
  const workspace = symbolPage.locator("[data-symbol-workspace]");
  await expect(workspace).toBeVisible();
  const timeframeBoard = symbolPage.getByRole("region", { name: "時間軸別データ" });
  await expect(timeframeBoard.locator("em")).toHaveCount(1);
  await expect(timeframeBoard.getByText("15m量倍率 3.4×", { exact: true })).toBeVisible();

  const topLevelOrder = await symbolPage.locator(":scope > *").evaluateAll((elements) =>
    elements.map(
      (element) =>
        element.getAttribute("aria-label") ??
        element.getAttribute("class")?.split(/\s+/)[0] ??
        element.tagName.toLowerCase()
    )
  );
  expect(topLevelOrder).toEqual([
    "symbol-top",
    "個別分析内を移動",
    "ALT 分析",
    "時間軸別データ",
    "補助情報",
    "back-to-analysis-top"
  ]);

  const sections = workspace.locator(":scope > [data-symbol-workspace-section]");
  await expect(sections).toHaveCount(6);
  expect(
    await sections.evaluateAll((elements) =>
      elements.map((element) => element.querySelector("h2")?.textContent?.trim() ?? "")
    )
  ).toEqual([
    "24h レンジ",
    "74h 条件",
    "品質と市場条件",
    "理由とリスク",
    "銘柄注記",
    "スナップショット"
  ]);

  const workspaceBox = await readBox(workspace);
  expect(workspaceBox.borderTopWidth).toBe("1px");
  expect(workspaceBox.borderRightWidth).toBe("1px");
  expect(workspaceBox.borderBottomWidth).toBe("1px");
  expect(workspaceBox.borderLeftWidth).toBe("1px");
  expect(workspaceBox.columnGap).toBe("0px");
  expect(workspaceBox.rowGap).toBe("0px");
  expect(workspaceBox.boxShadow).toBe("none");

  const sectionBoxes = await Promise.all(
    Array.from({ length: 6 }, (_, index) => readBox(sections.nth(index)))
  );
  for (const [index, box] of sectionBoxes.entries()) {
    expect(box.backgroundColor, `section ${index} background`).toBe("rgba(0, 0, 0, 0)");
    expect(box.borderRadius, `section ${index} radius`).toBe("0px");
    expect(box.boxShadow, `section ${index} shadow`).toBe("none");
    expect(box.borderTopWidth, `section ${index} top border`).toBe("0px");
    expect(box.borderLeftWidth, `section ${index} left border`).toBe("0px");
  }
  expect(sectionBoxes[0]?.top).toBeCloseTo(sectionBoxes[1]?.top ?? 0, 0);
  expect(sectionBoxes[0]?.right).toBeCloseTo(sectionBoxes[1]?.left ?? 0, 0);
  expect(sectionBoxes[0]?.width).toBeCloseTo(sectionBoxes[1]?.width ?? 0, 0);
  expect(sectionBoxes[2]?.top).toBeCloseTo(sectionBoxes[3]?.top ?? 0, 0);
  expect(sectionBoxes[2]?.right).toBeCloseTo(sectionBoxes[3]?.left ?? 0, 0);
  expect(sectionBoxes[4]?.width).toBeCloseTo(workspaceBox.width - 2, 0);
  expect(sectionBoxes[5]?.borderBottomWidth).toBe("0px");

  const nestedSurfaces = [workspace.locator(".fact-list > div").first()];
  for (const [index, surface] of nestedSurfaces.entries()) {
    const box = await readBox(surface);
    expect(box.backgroundColor, `nested surface ${index} background`).toBe("rgba(0, 0, 0, 0)");
    expect(box.boxShadow, `nested surface ${index} shadow`).toBe("none");
    expect(box.borderRadius, `nested surface ${index} radius`).toBe("0px");
  }

  const rangeTrack = workspace.locator(".range-track");
  if ((await rangeTrack.count()) > 0) {
    await expect(rangeTrack).toHaveAttribute("aria-hidden", "true");
  } else {
    await expect(workspace.getByText("レンジ未取得", { exact: true })).toBeVisible();
  }
  await expect(workspace.getByText("銘柄注記は、銘柄への注意・クセ・過去反応を残す監視用メモです。")).toBeVisible();
  await expect(workspace.getByText("データ時点", { exact: true })).toBeVisible();
});

test("uses dashboard sort-order labels in the Symbol ranking position", async ({ page }) => {
  await page.goto("/symbols/ALTUSDT?tf=15m");

  const monitoringRail = page.getByRole("complementary", { name: "監視材料" });
  const rankingHeading = monitoringRail.getByRole("heading", { name: "ランキング位置", exact: true });
  await expect(rankingHeading).toBeVisible();
  await expect(monitoringRail.locator(".rank-context dt")).toHaveText([
    "上昇順",
    "下落順",
    "売買代金",
    "出来高倍率"
  ]);
});

test("symbol support workspace stacks without gaps or horizontal overflow on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 900 });
  await page.goto("/symbols/THINUSDT?tf=15m");

  const workspace = page.locator("[data-symbol-workspace]");
  const sections = workspace.locator(":scope > [data-symbol-workspace-section]");
  await expect(sections).toHaveCount(6);
  const workspaceBox = await readBox(workspace);
  const sectionBoxes = await Promise.all(
    Array.from({ length: 6 }, (_, index) => readBox(sections.nth(index)))
  );

  for (const [index, box] of sectionBoxes.entries()) {
    expect(box.left, `mobile section ${index} left`).toBeCloseTo(workspaceBox.left + 1, 0);
    expect(box.width, `mobile section ${index} width`).toBeCloseTo(workspaceBox.width - 2, 0);
    expect(box.borderRightWidth, `mobile section ${index} right border`).toBe("0px");
    if (index > 0) {
      expect(box.top, `mobile section ${index} continuity`).toBeCloseTo(
        sectionBoxes[index - 1]?.bottom ?? 0,
        0
      );
    }
  }

  const overflow = await page.evaluate(() =>
    Math.max(0, document.documentElement.scrollWidth - window.innerWidth)
  );
  expect(overflow).toBe(0);
});

test("mobile symbol page jumps directly to long-form work areas and back to analysis", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/symbols/ALTUSDT?tf=15m");

  const sectionNavigation = page.getByRole("navigation", { name: "個別分析内を移動" });
  await expect(sectionNavigation).toBeVisible();
  expect(await sectionNavigation.evaluate((element) => getComputedStyle(element).position)).toBe(
    "sticky"
  );

  const jumpNames = [
    "チャート",
    "監視材料",
    "時間軸",
    "市場条件",
    "銘柄注記"
  ];
  for (const name of jumpNames) {
    await expect(sectionNavigation.getByRole("link", { name, exact: true })).toBeVisible();
  }

  const monitoringJump = sectionNavigation.getByRole("link", { name: "監視材料", exact: true });
  await monitoringJump.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#symbol-monitoring$/);
  const monitoringTarget = page.locator("#symbol-monitoring");
  await expect(monitoringTarget).toBeInViewport();
  await expect(monitoringTarget).toBeFocused();

  const backToTop = page.getByRole("link", { name: "分析上部へ戻る", exact: true });
  await backToTop.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#symbol-analysis-top$/);
  const analysisTop = page.locator("#symbol-analysis-top");
  await expect(analysisTop).toBeInViewport();
  await expect(analysisTop).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "一覧へ", exact: true })).toBeFocused();
});

test("past-note success stays scoped to the submitted symbol after client navigation", async ({ page }) => {
  await exercisePastNoteResponseAcrossSymbolNavigation(page, "success");
});

test("past-note failure stays scoped to the submitted symbol after client navigation", async ({ page }) => {
  await exercisePastNoteResponseAcrossSymbolNavigation(page, "failure");
});

test("preserves a newer same-symbol past-note draft after the pending response", async ({ page }) => {
  const suffix = `past-note-v2-${Date.now()}`;
  const submittedReason = `past note reason V1 ${suffix}`;
  const submittedNote = `past note V1 ${suffix}`;
  const newerReason = `past note reason V2 ${suffix}`;
  const newerNote = `past note V2 ${suffix}`;
  const gate = deferredGate();
  const settled = deferredGate();
  let postCalls = 0;
  let submittedBody: { symbol?: string; reason?: string; note?: string } | null = null;

  const routeHandler = async (route: Route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    postCalls += 1;
    submittedBody = route.request().postDataJSON() as {
      symbol?: string;
      reason?: string;
      note?: string;
    };
    try {
      await gate.wait;
      await route.fulfill({
        json: {
          notes: [
            {
              symbol: "ALTUSDT",
              reason: submittedReason,
              note: submittedNote,
              observedAt: "2026-07-18T07:00:00.000Z",
              expiresAt: "2026-08-17T07:00:00.000Z"
            }
          ]
        }
      });
    } finally {
      settled.release();
    }
  };

  await page.route("**/api/past-notes", routeHandler);
  try {
    await page.goto("/symbols/ALTUSDT?tf=15m");
    const panel = page.locator("#symbol-past-notes");
    const reasonInput = panel.getByLabel("理由", { exact: true });
    const noteInput = panel.getByLabel("メモ", { exact: true });
    await reasonInput.fill(submittedReason);
    await noteInput.fill(submittedNote);
    await panel.getByRole("button", { name: "銘柄注記を保存" }).click();
    await expect.poll(() => postCalls).toBe(1);
    expect(submittedBody).toEqual({
      symbol: "ALTUSDT",
      reason: submittedReason,
      note: submittedNote
    });

    await reasonInput.fill(newerReason);
    await noteInput.fill(newerNote);
    gate.release();

    await expect(panel.getByRole("status")).toHaveText(
      "送信時点の内容を保存しました。追加の変更は未保存です"
    );
    await expect(panel.locator(".note-list article").filter({ hasText: submittedReason })).toContainText(
      submittedNote
    );
    await expect(reasonInput).toHaveValue(newerReason);
    await expect(noteInput).toHaveValue(newerNote);
  } finally {
    gate.release();
    if (postCalls > 0) await settled.wait;
    await page.unroute("**/api/past-notes", routeHandler);
  }
});

test("uses the normal past-note notice after a route-reset round trip with no new draft", async ({
  page
}) => {
  await exercisePastNoteRoundTripToSubmittedSymbol(page, false);
});

test("preserves a newer past-note draft edited after returning to the submitted symbol", async ({
  page
}) => {
  await exercisePastNoteRoundTripToSubmittedSymbol(page, true);
});
