import {
  expect,
  test,
  type Locator,
  type Page
} from "@playwright/test";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { resolveWebTestStatePaths } from "../../test-state-paths";

const e2ePaths = resolveWebTestStatePaths("e2e");
const pastNotesPath = resolve(e2ePaths.pastNotesDir, "current.json");

type RootOverflowMeasurement = {
  selector: "html";
  viewportWidth: number;
  clientWidth: number;
  scrollWidth: number;
  overflowPx: number;
};

type ElementBoxMeasurement = {
  selector: string;
  accessibleName: string;
  x: number;
  y: number;
  width: number;
  height: number;
};

type InteractiveTargetMeasurement = ElementBoxMeasurement & {
  tagName: string;
};

type TouchTargetMeasurement = InteractiveTargetMeasurement & {
  sourceTagName: string;
};

type SectionOrderEntry = {
  index: number;
  selector: string;
  accessibleName: string;
};

type ElementOverflowMeasurement = {
  selector: string;
  accessibleName: string;
  clientWidth: number;
  scrollWidth: number;
  overflowPx: number;
};

type LayoutSnapshotRow = {
  symbol: string;
  [key: string]: unknown;
};

type LayoutSnapshot = {
  rows: LayoutSnapshotRow[];
  summary: { counts: Record<string, number>; [key: string]: unknown };
  rankings: {
    timeframes: Record<string, Record<string, Array<{ symbol: string; value: number }>>>;
    meta: {
      timeframes: Record<
        string,
        Record<string, { limit: number; totalEligible: number; [key: string]: unknown }>
      >;
    };
  };
  [key: string]: unknown;
};

const requiredRootThemeTokens = [
  "--bg",
  "--bg-alt",
  "--surface",
  "--panel",
  "--panel-solid",
  "--panel-strong",
  "--panel-selected",
  "--line",
  "--line-strong",
  "--text",
  "--muted",
  "--subtle",
  "--focus",
  "--primary",
  "--focus-on",
  "--up",
  "--down",
  "--warning",
  "--warning-border",
  "--quality-good",
  "--quality-risk",
  "--chip-line",
  "--chip-neutral",
  "--chart-surface",
  "--chart-text",
  "--chart-grid",
  "--chart-border",
  "--chart-up",
  "--chart-down",
  "--chart-focus",
  "--chart-volume-up",
  "--chart-volume-down",
  "--control-height-dense",
  "--control-height-touch",
  "--control-height-primary-touch",
  "--focus-ring-width",
  "--focus-ring-offset"
] as const;

type ThemeSnapshot = {
  tokens: Record<(typeof requiredRootThemeTokens)[number], string>;
  body: {
    margin: string;
    backgroundColor: string;
    color: string;
    fontFamily: string;
    watchdeckSansReady: boolean;
    watchdeckSansRequestedFaces: number;
    watchdeckSansFaceStatuses: string[];
  };
};

type RuntimeColorMeasurement = {
  actualColor: string;
  expectedColor: string;
  backgroundColor: string;
  alpha: number;
  contrastRatio: number;
};

type PressedSelectionMeasurement = {
  isActive: boolean;
  backgroundColor: string;
  color: string;
  expectedBackgroundColor: string;
  expectedColor: string;
  contrastRatio: number;
};

function writeJsonAtomically(path: string, value: unknown) {
  mkdirSync(dirname(path), { recursive: true });
  const tempPath = `${path}.${process.pid}.tmp`;
  writeFileSync(tempPath, `${JSON.stringify(value)}\n`, "utf-8");
  renameSync(tempPath, path);
}

async function readThemeSnapshot(page: Page): Promise<ThemeSnapshot> {
  return page.evaluate(async (tokenNames) => {
    const requestedFaces = await document.fonts.load('16px "Watchdeck Sans"', "準備監視板 ABC 123");
    await document.fonts.ready;
    const watchdeckSansFaceStatuses: string[] = [];
    document.fonts.forEach((face) => {
      if (face.family.replace(/["']/g, "") === "Watchdeck Sans") {
        watchdeckSansFaceStatuses.push(face.status);
      }
    });
    const rootStyle = getComputedStyle(document.documentElement);
    const bodyStyle = getComputedStyle(document.body);
    return {
      tokens: Object.fromEntries(
        tokenNames.map((tokenName) => [tokenName, rootStyle.getPropertyValue(tokenName).trim()])
      ) as ThemeSnapshot["tokens"],
      body: {
        margin: bodyStyle.margin,
        backgroundColor: bodyStyle.backgroundColor,
        color: bodyStyle.color,
        fontFamily: bodyStyle.fontFamily,
        watchdeckSansReady: document.fonts.check('16px "Watchdeck Sans"', "準備監視板 ABC 123"),
        watchdeckSansRequestedFaces: requestedFaces.length,
        watchdeckSansFaceStatuses
      }
    };
  }, requiredRootThemeTokens);
}

async function exposeHorizontalOverflow(page: Page) {
  await page.addStyleTag({
    content: `
      html,
      body {
        overflow-x: visible !important;
      }

      .intel-grid {
        overflow: visible !important;
      }
    `
  });
}

async function assertRegionsFitViewport(
  page: Page,
  regions: Array<[name: string, locator: Locator]>,
  viewportWidth: number,
  surface: string
) {
  for (const [name, locator] of regions) {
    await expect(locator, `${surface} ${viewportWidth}px ${name}`).toBeVisible();
    const box = await measureElementBox(locator);
    const overflow = await measureElementOverflow(locator);
    expect(box.x, `${surface} ${viewportWidth}px ${name} left: ${JSON.stringify(box)}`).toBeGreaterThanOrEqual(
      -1
    );
    expect(
      box.x + box.width,
      `${surface} ${viewportWidth}px ${name} right: ${JSON.stringify(box)}`
    ).toBeLessThanOrEqual(viewportWidth + 1);
    expect(
      overflow.overflowPx,
      `${surface} ${viewportWidth}px ${name} overflow: ${JSON.stringify(overflow)}`
    ).toBe(0);
  }
}

export async function measureRootOverflow(page: Page): Promise<RootOverflowMeasurement> {
  return page.evaluate(() => {
    const root = document.documentElement;
    const viewportWidth = window.innerWidth;
    return {
      selector: "html" as const,
      viewportWidth,
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      overflowPx: Math.max(0, root.scrollWidth - viewportWidth)
    };
  });
}

export async function measureElementBox(locator: Locator): Promise<ElementBoxMeasurement> {
  const selector = locator.toString();
  const measurement = await locator.first().evaluate((element) => {
    const box = element.getBoundingClientRect();
    const accessibleName =
      element.getAttribute("aria-label") ?? element.textContent?.replace(/\s+/g, " ").trim() ?? "";
    return {
      accessibleName,
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height
    };
  });
  return { selector, ...measurement };
}

async function measureElementOverflow(locator: Locator): Promise<ElementOverflowMeasurement> {
  const selector = locator.toString();
  const measurement = await locator.first().evaluate((element) => ({
    accessibleName:
      element.getAttribute("aria-label") ?? element.textContent?.replace(/\s+/g, " ").trim() ?? "",
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
    overflowPx: Math.max(0, element.scrollWidth - element.clientWidth)
  }));
  return { selector, ...measurement };
}

export async function collectInteractiveTargets(
  page: Page
): Promise<InteractiveTargetMeasurement[]> {
  return page.locator('a[href], button, input, select, textarea, summary, [tabindex="0"]').evaluateAll(
    (elements) =>
      elements.flatMap((element, index) => {
        const box = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        if (box.width === 0 || box.height === 0 || style.visibility === "hidden") return [];
        const accessibleName =
          element.getAttribute("aria-label") ??
          element.textContent?.replace(/\s+/g, " ").trim() ??
          "";
        return [
          {
            selector: `${element.tagName.toLowerCase()}[layout-index="${index}"]`,
            accessibleName,
            tagName: element.tagName.toLowerCase(),
            x: box.x,
            y: box.y,
            width: box.width,
            height: box.height
          }
        ];
      })
  );
}

async function collectTouchTargets(root: Locator): Promise<TouchTargetMeasurement[]> {
  return root
    .locator('a[href], button, input:not([type="hidden"]), select, textarea, summary')
    .evaluateAll((elements) => {
      const measured = new Set<Element>();
      return elements.flatMap((element, index) => {
        const inputType = element instanceof HTMLInputElement ? element.type : "";
        const target =
          inputType === "checkbox" || inputType === "radio"
            ? element.closest("label") ?? element
            : element;
        if (measured.has(target)) return [];
        measured.add(target);
        const box = target.getBoundingClientRect();
        const style = getComputedStyle(target);
        if (
          box.width === 0 ||
          box.height === 0 ||
          style.display === "none" ||
          style.visibility === "hidden"
        ) {
          return [];
        }
        const accessibleName =
          element.getAttribute("aria-label") ??
          target.getAttribute("aria-label") ??
          target.textContent?.replace(/\s+/g, " ").trim() ??
          "";
        return [
          {
            selector: `${target.tagName.toLowerCase()}[touch-index="${index}"]`,
            accessibleName,
            tagName: target.tagName.toLowerCase(),
            sourceTagName: element.tagName.toLowerCase(),
            x: box.x,
            y: box.y,
            width: box.width,
            height: box.height
          }
        ];
      });
    });
}

function assertTouchTargets(
  measurements: TouchTargetMeasurement[],
  viewportWidth: number,
  surface: string
) {
  const undersized = measurements.filter(
    (measurement) => measurement.width < 44 || measurement.height < 44
  );
  if (undersized.length === 0) return;
  throw new Error(
    [
      `${surface} touch target assertion failed at ${viewportWidth}px`,
      `undersized=${undersized.length}/${measurements.length}`,
      ...undersized.slice(0, 12).map(
        (measurement) =>
          `${measurement.selector} ${JSON.stringify(measurement.accessibleName)} ` +
          `${measurement.width.toFixed(1)}x${measurement.height.toFixed(1)}`
      )
    ].join("; ")
  );
}

async function assertSingleLineActions(page: Page, viewportWidth: number, surface: string) {
  const measurements = await page.locator("[data-single-line-action]").evaluateAll((elements) =>
    elements.flatMap((element, index) => {
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      if (box.width === 0 || box.height === 0 || style.visibility === "hidden") return [];
      return [
        {
          index,
          accessibleName:
            element.getAttribute("aria-label") ??
            element.textContent?.replace(/\s+/g, " ").trim() ??
            "",
          whiteSpace: style.whiteSpace,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth
        }
      ];
    })
  );
  expect(measurements.length, `${surface} ${viewportWidth}px single-line action coverage`).toBeGreaterThan(
    0
  );
  const invalid = measurements.filter(
    (measurement) =>
      measurement.whiteSpace !== "nowrap" || measurement.scrollWidth > measurement.clientWidth + 1
  );
  expect(
    invalid,
    `${surface} ${viewportWidth}px single-line actions: ${JSON.stringify(invalid)}`
  ).toEqual([]);
}

async function assertVisibleFocusRing(locator: Locator, context: string) {
  await locator.focus();
  const focusStyle = await locator.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth),
      outlineOffset: Number.parseFloat(style.outlineOffset)
    };
  });
  expect(focusStyle.outlineStyle, `${context}: ${JSON.stringify(focusStyle)}`).not.toBe("none");
  expect(focusStyle.outlineWidth, `${context}: ${JSON.stringify(focusStyle)}`).toBeGreaterThanOrEqual(
    2
  );
}

async function measureSemanticFocusRing(locator: Locator): Promise<RuntimeColorMeasurement> {
  await locator.scrollIntoViewIfNeeded();
  await locator.focus();
  return locator.evaluate((element) => {
    const normalizeColor = (value: string) => {
      const probe = document.createElement("span");
      probe.style.color = value;
      document.body.append(probe);
      const color = getComputedStyle(probe).color;
      probe.remove();
      return color;
    };
    const channels = (value: string) => {
      const values = value.match(/[\d.]+/g)?.map(Number) ?? [];
      return {
        red: values[0] ?? 0,
        green: values[1] ?? 0,
        blue: values[2] ?? 0,
        alpha: values[3] ?? 1
      };
    };
    const luminance = (value: string) => {
      const color = channels(value);
      const linear = [color.red, color.green, color.blue].map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
    };
    const contrast = (first: string, second: string) => {
      const firstLuminance = luminance(first);
      const secondLuminance = luminance(second);
      return (
        (Math.max(firstLuminance, secondLuminance) + 0.05) /
        (Math.min(firstLuminance, secondLuminance) + 0.05)
      );
    };
    const style = getComputedStyle(element);
    const actualColor = normalizeColor(style.outlineColor);
    const expectedColor = normalizeColor(
      getComputedStyle(document.documentElement).getPropertyValue("--focus")
    );
    const backgroundColor = (() => {
      for (let node = element.parentElement; node; node = node.parentElement) {
        const candidate = normalizeColor(getComputedStyle(node).backgroundColor);
        if (channels(candidate).alpha === 1) return candidate;
      }
      return normalizeColor(getComputedStyle(document.body).backgroundColor);
    })();
    return {
      actualColor,
      expectedColor,
      backgroundColor,
      alpha: channels(actualColor).alpha,
      contrastRatio: contrast(actualColor, backgroundColor)
    };
  });
}

async function assertSemanticFocusRing(locator: Locator, context: string) {
  await expect(locator, `${context}: focus target must be rendered`).toBeVisible();
  const measurement = await measureSemanticFocusRing(locator);
  expect(measurement.actualColor, `${context}: ${JSON.stringify(measurement)}`).toBe(
    measurement.expectedColor
  );
  expect(measurement.alpha, `${context}: ${JSON.stringify(measurement)}`).toBe(1);
  expect(measurement.contrastRatio, `${context}: ${JSON.stringify(measurement)}`).toBeGreaterThanOrEqual(
    3
  );
}

async function measurePressedSelection(
  page: Page,
  locator: Locator
): Promise<PressedSelectionMeasurement> {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (!box) throw new Error(`pressed selection has no box: ${locator}`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  try {
    return await locator.evaluate((element) => {
      const normalizeColor = (value: string) => {
        const probe = document.createElement("span");
        probe.style.color = value;
        document.body.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      };
      const channels = (value: string) => {
        const values = value.match(/[\d.]+/g)?.map(Number) ?? [];
        return [values[0] ?? 0, values[1] ?? 0, values[2] ?? 0];
      };
      const luminance = (value: string) => {
        const linear = channels(value).map((channel) => {
          const normalized = channel / 255;
          return normalized <= 0.04045
            ? normalized / 12.92
            : ((normalized + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
      };
      const contrast = (first: string, second: string) => {
        const firstLuminance = luminance(first);
        const secondLuminance = luminance(second);
        return (
          (Math.max(firstLuminance, secondLuminance) + 0.05) /
          (Math.min(firstLuminance, secondLuminance) + 0.05)
        );
      };
      const style = getComputedStyle(element);
      const rootStyle = getComputedStyle(document.documentElement);
      const backgroundColor = normalizeColor(style.backgroundColor);
      const color = normalizeColor(style.color);
      return {
        isActive: element.matches(":active"),
        backgroundColor,
        color,
        expectedBackgroundColor: normalizeColor(rootStyle.getPropertyValue("--focus")),
        expectedColor: normalizeColor(rootStyle.getPropertyValue("--focus-on")),
        contrastRatio: contrast(color, backgroundColor)
      };
    });
  } finally {
    await page.mouse.move(0, 0);
    await page.mouse.up();
  }
}

async function assertPressedSelectionContrast(page: Page, locator: Locator, context: string) {
  await expect(locator, `${context}: selected control must be rendered`).toBeVisible();
  const measurement = await measurePressedSelection(page, locator);
  expect(measurement.isActive, `${context}: ${JSON.stringify(measurement)}`).toBe(true);
  expect(measurement.backgroundColor, `${context}: ${JSON.stringify(measurement)}`).toBe(
    measurement.expectedBackgroundColor
  );
  expect(measurement.color, `${context}: ${JSON.stringify(measurement)}`).toBe(
    measurement.expectedColor
  );
  expect(measurement.contrastRatio, `${context}: ${JSON.stringify(measurement)}`).toBeGreaterThanOrEqual(
    4.5
  );
}

export async function readSectionOrder(page: Page): Promise<SectionOrderEntry[]> {
  return page
    .locator("main section[aria-label], main aside[aria-label], main [role='region'][aria-label]")
    .evaluateAll((elements) =>
      elements.map((element, index) => ({
        index,
        selector: `${element.tagName.toLowerCase()}[section-index="${index}"]`,
        accessibleName:
          element.getAttribute("aria-label") ??
          element.querySelector("h1, h2, h3")?.textContent?.replace(/\s+/g, " ").trim() ??
          ""
      }))
    );
}

function assertBoxFitsWidth(
  measurement: ElementBoxMeasurement,
  expectedMaxWidth: number,
  viewportWidth: number
) {
  if (measurement.width <= expectedMaxWidth) return;
  throw new Error(
    [
      "layout width assertion failed",
      `viewport=${viewportWidth}px`,
      `selector=${measurement.selector}`,
      `accessibleName=${JSON.stringify(measurement.accessibleName)}`,
      `actual=${measurement.width}px`,
      `expected<=${expectedMaxWidth}px`
    ].join("; ")
  );
}

test("responsive layout harness reports selector, name, viewport, actual, and expected", () => {
  const invalidFixture: ElementBoxMeasurement = {
    selector: '[data-layout-fixture="invalid"]',
    accessibleName: "invalid width fixture",
    x: 0,
    y: 0,
    width: 420,
    height: 44
  };

  expect(() => assertBoxFitsWidth(invalidFixture, 320, 320)).toThrow(
    'viewport=320px; selector=[data-layout-fixture="invalid"]; accessibleName="invalid width fixture"; actual=420px; expected<=320px'
  );
});

test("fixture dashboard loads through the responsive layout harness", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "ローカル市場監視" })).toBeVisible();

  const root = await measureRootOverflow(page);
  const watchlist = await measureElementBox(
    page.getByRole("region", { name: "精密監視リスト" })
  );
  const targets = await collectInteractiveTargets(page);
  const sections = await readSectionOrder(page);

  expect(root.selector).toBe("html");
  expect(root.viewportWidth).toBeGreaterThan(0);
  expect(root.clientWidth).toBeGreaterThan(0);
  expect(root.scrollWidth).toBeGreaterThanOrEqual(root.clientWidth);
  expect(watchlist.accessibleName).toBe("精密監視リスト");
  expect(watchlist.width).toBeGreaterThan(0);
  expect(targets.length).toBeGreaterThan(0);
  expect(targets.some((target) => target.accessibleName.includes("15m"))).toBe(true);
  expect(sections.some((section) => section.accessibleName === "精密監視リスト")).toBe(true);
  expect(sections.some((section) => section.accessibleName === "選択銘柄の詳細")).toBe(true);
});

test("market row exposes all six visible timeframe values in its accessible name", async ({
  page
}) => {
  await page.goto("/");

  const altRow = page.locator(
    '[data-market-row][data-symbol="ALTUSDT"] [data-row-select]'
  );
  await expect(altRow).toHaveAttribute(
    "aria-label",
    /時間軸別変化 5m 0\.4%、15m 2\.1%、1h 0\.8%、4h 2\.2%、24h 3\.1%、74h 8\.4%/
  );
});

test("mobile candidate ranking keeps every symbol identity readable", async ({ page }) => {
  const originalText = readFileSync(e2ePaths.snapshotPath, "utf-8");
  const snapshot = JSON.parse(originalText) as LayoutSnapshot;
  const longSymbol = "1000000BABYDOGEUSDT";
  const longDisplaySymbol = "1000000BABYDOGE";
  const metricIds = ["changeUp", "changeDown", "turnoverTop", "volumeUp"] as const;

  for (const metric of metricIds) {
    const ranking = snapshot.rankings.timeframes["15m"]?.[metric];
    if (!ranking?.[0]) throw new Error(`15m ${metric} ranking fixture is missing`);
    const shortItem = ranking[0];
    ranking.splice(0, ranking.length, { ...shortItem, symbol: longSymbol }, shortItem);
    const meta = snapshot.rankings.meta.timeframes["15m"]?.[metric];
    if (!meta) throw new Error(`15m ${metric} ranking meta fixture is missing`);
    meta.totalEligible = 2;
  }

  writeJsonAtomically(e2ePaths.snapshotPath, snapshot);
  try {
    for (const viewport of [
      { width: 320, height: 568 },
      { width: 375, height: 667 },
      { width: 414, height: 896 }
    ]) {
      await test.step(`${viewport.width}px`, async () => {
        await page.setViewportSize(viewport);
        await page.goto("/");
        await page
          .locator(".ranking-area")
          .getByRole("button", { name: "15m", exact: true })
          .click();
        const candidateRanking = page.getByRole("region", { name: "15m ランキング" });
        const tabs = candidateRanking.getByRole("tab");
        await expect(tabs).toHaveCount(4);
        for (const tabName of ["上昇", "下落", "売買代金", "15分量倍率"]) {
          await candidateRanking.getByRole("tab", { name: tabName, exact: true }).click();
          const activePanel = candidateRanking.getByRole("tabpanel");
          await expect(activePanel.locator(`.rank-row > span[title="${longSymbol}"]`)).toBeVisible();
        }
        await candidateRanking.getByRole("tab", { name: "上昇", exact: true }).click();
        await exposeHorizontalOverflow(page);

        const rankingBody = page.locator(".mobile-rankings");
        const symbols = rankingBody.locator(".rank-panel:not([hidden]) .rank-row > span[title]");
        const longSymbols = rankingBody.locator(`.rank-row > span[title="${longSymbol}"]`);
        await expect(longSymbols).toHaveCount(metricIds.length);
        const measurements = await symbols.evaluateAll((nodes) =>
          nodes.map((node) => {
            const row = node.closest<HTMLElement>(".rank-row");
            if (!row) throw new Error("candidate ranking row is missing");
            const style = getComputedStyle(node);
            const box = node.getBoundingClientRect();
            const rowBox = row.getBoundingClientRect();
            return {
              symbol: node.getAttribute("title") ?? "",
              text: node.textContent?.trim() ?? "",
              clientWidth: node.clientWidth,
              scrollWidth: node.scrollWidth,
              textOverflow: style.textOverflow,
              boxLeft: box.left,
              boxRight: box.right,
              rowLeft: rowBox.left,
              rowRight: rowBox.right,
              rowHeight: rowBox.height
            };
          })
        );

        expect(
          measurements
            .filter((measurement) => measurement.symbol === longSymbol)
            .every((measurement) => measurement.text === longDisplaySymbol),
          `${viewport.width}px incomplete candidate identity: ${JSON.stringify(measurements)}`
        ).toBe(true);
        expect(
          measurements.some((measurement) => measurement.symbol !== longSymbol),
          `${viewport.width}px short candidate fixture coverage: ${JSON.stringify(measurements)}`
        ).toBe(true);
        expect(
          measurements.every(
            (measurement) =>
              measurement.scrollWidth <= measurement.clientWidth + 1 &&
              measurement.textOverflow !== "ellipsis" &&
              measurement.boxLeft >= measurement.rowLeft - 1 &&
              measurement.boxRight <= measurement.rowRight + 1
          ),
          `${viewport.width}px truncated candidate identity: ${JSON.stringify(measurements)}`
        ).toBe(true);
        expect(
          measurements.every((measurement) => measurement.rowHeight >= 44),
          `${viewport.width}px candidate target height: ${JSON.stringify(measurements)}`
        ).toBe(true);

        const root = await measureRootOverflow(page);
        expect(root.overflowPx, `${viewport.width}px root overflow: ${JSON.stringify(root)}`).toBe(0);
      });
    }
  } finally {
    writeFileSync(e2ePaths.snapshotPath, originalText, "utf-8");
  }
});

test("mobile candidate tabs use automatic roving activation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const ranking = page.getByRole("region", { name: "15m ランキング" });
  const up = ranking.getByRole("tab", { name: "上昇", exact: true });
  const down = ranking.getByRole("tab", { name: "下落", exact: true });
  const ratio = ranking.getByRole("tab", { name: "15分量倍率", exact: true });
  await ratio.click();
  const directionStyles = await Promise.all(
    [up, down].map((tab) =>
      tab.evaluate((element) => {
        const normalizeColor = (value: string) => {
          const probe = document.createElement("span");
          probe.style.color = value;
          document.body.append(probe);
          const color = getComputedStyle(probe).color;
          probe.remove();
          return color;
        };
        const rootStyle = getComputedStyle(document.documentElement);
        const token = element.textContent?.trim() === "上昇" ? "--up" : "--down";
        return {
          color: getComputedStyle(element).color,
          marker: getComputedStyle(element).boxShadow,
          expected: normalizeColor(rootStyle.getPropertyValue(token))
        };
      })
    )
  );
  expect(directionStyles[0].color).toBe(directionStyles[0].expected);
  expect(directionStyles[1].color).toBe(directionStyles[1].expected);
  expect(directionStyles[0].marker).toContain(directionStyles[0].expected);
  expect(directionStyles[1].marker).toContain(directionStyles[1].expected);
  await up.click();
  await expect(up).toHaveAttribute("tabindex", "0");
  await up.focus();
  await up.press("ArrowRight");
  await expect(down).toBeFocused();
  await expect(down).toHaveAttribute("aria-selected", "true");
  await down.press("End");
  await expect(ratio).toBeFocused();
  await expect(ratio).toHaveAttribute("aria-selected", "true");
  await ratio.press("ArrowRight");
  await expect(up).toBeFocused();
  await expect(up).toHaveAttribute("aria-selected", "true");
});

test("320px timeframe controls form balanced three-by-two groups", async ({ page }) => {
  const routesAndSelectors = [
    ["/", ".ranking-area .timeframe-strip > button"],
    ["/symbols/ALTUSDT?tf=15m", ".timeframe-bar > a"]
  ] as const;

  await page.setViewportSize({ width: 320, height: 844 });
  for (const [route, selector] of routesAndSelectors) {
    await page.goto(route);
    const rowCounts = await page.locator(selector).evaluateAll((elements) => {
      const counts = new Map<number, number>();
      for (const element of elements) {
        const top = Math.round(element.getBoundingClientRect().top);
        counts.set(top, (counts.get(top) ?? 0) + 1);
      }
      return [...counts.values()].sort((left, right) => left - right);
    });
    expect(rowCounts, `${route} timeframe row counts`).toEqual([3, 3]);
  }
});

test("mobile dashboard compacts source service and runtime into one status strip", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto("/");

  const statusStack = page.locator(".status-stack");
  const statusItems = statusStack.locator(":scope > *");
  await expect(statusItems).toHaveCount(3);
  const boxes = await statusItems.evaluateAll((elements) =>
    elements.map((element) => {
      const box = element.getBoundingClientRect();
      return { top: box.top, bottom: box.bottom, width: box.width };
    })
  );
  expect(
    Math.max(...boxes.map((box) => box.top)) - Math.min(...boxes.map((box) => box.top))
  ).toBeLessThanOrEqual(1);
  expect(
    Math.max(...boxes.map((box) => box.bottom)) - Math.min(...boxes.map((box) => box.top))
  ).toBeLessThanOrEqual(120);
  expect(boxes.every((box) => box.width >= 80)).toBe(true);
  const sourceStatus = statusStack.locator(".source-banner strong");
  const serviceStatus = statusStack.locator(".service-badge strong");
  await expect(sourceStatus).toHaveText("正常");
  await expect(serviceStatus).toHaveText("Service 状態なし");
  for (const status of [sourceStatus, serviceStatus]) {
    await expect(status).toHaveAttribute("role", "status");
    await expect(status).toHaveAttribute("aria-live", "polite");
    await expect(status).toHaveAttribute("aria-atomic", "true");
  }
  await expect(statusStack.getByText("LOCAL COMMANDS DISABLED", { exact: true })).toBeVisible();
});

test("dashboard and symbol routes share required root theme tokens and body base", async ({ page }) => {
  const snapshots: ThemeSnapshot[] = [];
  for (const route of ["/", "/symbols/ALTUSDT?tf=15m"]) {
    await page.goto(route);
    snapshots.push(await readThemeSnapshot(page));
  }

  for (const [index, snapshot] of snapshots.entries()) {
    const missing = requiredRootThemeTokens.filter((tokenName) => !snapshot.tokens[tokenName]);
    expect(missing, `route index ${index} missing root theme tokens`).toEqual([]);
    expect(snapshot.body.margin).toBe("0px");
    expect(snapshot.body.backgroundColor).toBe("rgb(7, 9, 8)");
    expect(snapshot.body.color).toBe("rgb(243, 245, 237)");
    expect(snapshot.body.fontFamily).toContain("Watchdeck Sans");
    expect(snapshot.body.watchdeckSansReady, `route index ${index} Watchdeck Sans readiness`).toBe(
      true
    );
    expect(
      snapshot.body.watchdeckSansRequestedFaces,
      `route index ${index} Watchdeck Sans requested faces`
    ).toBeGreaterThan(0);
    expect(
      snapshot.body.watchdeckSansFaceStatuses,
      `route index ${index} Watchdeck Sans FontFace status`
    ).not.toHaveLength(0);
    expect(
      snapshot.body.watchdeckSansFaceStatuses.every((status) => status === "loaded"),
      `route index ${index} Watchdeck Sans FontFace status: ${JSON.stringify(snapshot.body.watchdeckSansFaceStatuses)}`
    ).toBe(true);
  }

  expect(snapshots[1]?.tokens).toEqual(snapshots[0]?.tokens);
});

test("compact dashboard and symbol controls keep 44px targets, one-line actions, and visible focus", async ({
  page
}) => {
  test.setTimeout(120_000);
  const widths = [320, 375, 414, 768];

  for (const width of widths) {
    await test.step(`dashboard ${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      const terminal = page.locator("main.terminal");
      assertTouchTargets(await collectTouchTargets(terminal), width, "dashboard");
      await assertSingleLineActions(page, width, "dashboard");
      const refresh = page.getByRole("button", { name: "service snapshotを更新" });
      await expect(refresh).toHaveAttribute("aria-busy", "false");
      await expect(refresh).toContainText("Snapshot更新");
      await assertVisibleFocusRing(refresh, `dashboard refresh ${width}px`);
    });

    await test.step(`symbol ${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/symbols/ALTUSDT?tf=15m");
      const symbolPage = page.locator("main.symbol-page");
      assertTouchTargets(await collectTouchTargets(symbolPage), width, "symbol");
      await assertSingleLineActions(page, width, "symbol");
      await assertVisibleFocusRing(
        page.getByRole("link", { name: "一覧へ" }),
        `symbol back link ${width}px`
      );
    });
  }
});

test("symbol page keeps one chart frame and compact mobile analysis context", async ({ page }) => {
  test.setTimeout(120_000);

  for (const width of [320, 375, 414]) {
    await test.step(`${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/symbols/THINUSDT?tf=15m");

      const symbolPage = page.locator("main.symbol-page");
      const analysis = page.getByRole("region", { name: "THIN 分析" });
      const chartStage = page.getByRole("region", { name: "主チャート" });
      const chart = page.getByRole("region", { name: "THIN チャート" });
      const monitoring = page.getByRole("complementary", { name: "監視材料" });
      const timeframeBoard = page.getByRole("region", { name: "時間軸別データ" });
      const intel = page.getByRole("region", { name: "補助情報" });

      await expect(symbolPage.getByText("symbol analysis", { exact: true })).toHaveCount(0);
      await expect(monitoring.getByText("decision", { exact: true })).toHaveCount(0);
      await expect(timeframeBoard.getByText("timeframe scan", { exact: true })).toHaveCount(0);
      await expect(monitoring.locator(".monitoring-summary")).toBeVisible();
      await expect(monitoring.getByText("品質", { exact: true })).toHaveCount(0);
      await expect(monitoring.getByText("活動phase", { exact: true })).toBeVisible();
      await expect(monitoring.getByText("15m", { exact: true })).toBeVisible();
      await expect(monitoring.getByText("監視除外候補", { exact: true })).toBeVisible();

      const root = await measureRootOverflow(page);
      expect(root.overflowPx, `${width}px symbol root: ${JSON.stringify(root)}`).toBe(0);

      const chartFrames = await page.evaluate(() => {
        const stage = document.querySelector<HTMLElement>(".chart-stage");
        const card = document.querySelector<HTMLElement>(".chart-stage .chart-card.analysis");
        if (!stage || !card) throw new Error("symbol chart frame missing");
        const stageStyle = getComputedStyle(stage);
        const cardStyle = getComputedStyle(card);
        return {
          stage: [
            stageStyle.borderTopWidth,
            stageStyle.borderRightWidth,
            stageStyle.borderBottomWidth,
            stageStyle.borderLeftWidth
          ],
          card: [
            cardStyle.borderTopWidth,
            cardStyle.borderRightWidth,
            cardStyle.borderBottomWidth,
            cardStyle.borderLeftWidth
          ],
          cardBackground: cardStyle.backgroundColor
        };
      });
      expect(chartFrames.stage).toEqual(["1px", "1px", "1px", "1px"]);
      expect(chartFrames.card).toEqual(["0px", "0px", "0px", "0px"]);
      expect(chartFrames.cardBackground).toBe("rgba(0, 0, 0, 0)");

      const analysisChildren = await analysis.locator(":scope > *").evaluateAll((elements) =>
        elements.map(
          (element) =>
            element.getAttribute("aria-label") ??
            element.getAttribute("class") ??
            element.tagName.toLowerCase()
        )
      );
      expect(analysisChildren).toEqual(["主チャート", "監視材料"]);
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
        "THIN 分析",
        "時間軸別データ",
        "補助情報",
        "back-to-analysis-top"
      ]);

      await expect(chart).toBeVisible();
      await expect(intel).toBeVisible();
      await expect(timeframeBoard.getByRole("link")).toHaveCount(6);
      await expect(timeframeBoard.getByRole("link", { name: /15m/ })).toHaveAttribute(
        "aria-current",
        "page"
      );

      const mobileGrids = await page.evaluate(() => {
        const rank = document.querySelector<HTMLElement>(".monitoring-rail .rank-context");
        const summary = document.querySelector<HTMLElement>(".monitoring-rail .monitoring-summary");
        const board = document.querySelector<HTMLElement>(".timeframe-board .tf-grid");
        if (!rank || !summary || !board) throw new Error("symbol mobile grid missing");
        const boardRows = new Set(
          Array.from(board.querySelectorAll("a")).map((link) =>
            Math.round(link.getBoundingClientRect().top)
          )
        );
        return {
          rankColumns: getComputedStyle(rank).gridTemplateColumns.split(" ").length,
          summaryColumns: getComputedStyle(summary).gridTemplateColumns.split(" ").length,
          boardColumns: getComputedStyle(board).gridTemplateColumns.split(" ").length,
          boardRows: boardRows.size
        };
      });
      expect(mobileGrids.rankColumns).toBe(2);
      expect(mobileGrids.summaryColumns).toBe(2);
      expect(mobileGrids.boardColumns).toBe(2);
      expect(mobileGrids.boardRows).toBeLessThanOrEqual(3);

      for (const target of [
        page.getByRole("link", { name: "一覧へ" }),
        chartStage.getByRole("link", { name: "15m", exact: true }),
        chartStage.getByRole("link", { name: "提供元" })
      ]) {
        const box = await measureElementBox(target);
        expect(box.width, `${width}px ${box.accessibleName} width`).toBeGreaterThanOrEqual(44);
        expect(box.height, `${width}px ${box.accessibleName} height`).toBeGreaterThanOrEqual(44);
      }
    });
  }
});

test("a wide coarse pointer surface keeps touch targets without inflating fine-pointer density", async ({
  browser,
  page
}) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  const fineDensity = {
    category: await measureElementBox(
      page.getByRole("complementary", { name: "分類" }).getByRole("button").first()
    ),
    timeframe: await measureElementBox(
      page.getByRole("region", { name: /ランキング/ }).getByRole("button", { name: "15m" })
    ),
    view: await measureElementBox(
      page.getByRole("region", { name: "精密監視リスト" }).getByRole("button", { name: "標準" })
    )
  };
  expect(fineDensity.category.height).toBeLessThanOrEqual(38);
  expect(fineDensity.timeframe.height).toBeLessThanOrEqual(34);
  expect(fineDensity.view.height).toBeLessThanOrEqual(34);

  const coarseContext = await browser.newContext({
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1200, height: 900 },
    hasTouch: true
  });
  const coarsePage = await coarseContext.newPage();
  try {
    await coarsePage.goto("/");
    expect(
      await coarsePage.evaluate(() => matchMedia("(any-pointer: coarse)").matches),
      "Playwright coarse-pointer fixture"
    ).toBe(true);
    assertTouchTargets(
      await collectTouchTargets(coarsePage.locator("main.terminal")),
      1200,
      "dashboard coarse pointer"
    );
    await coarsePage.goto("/symbols/ALTUSDT?tf=15m");
    assertTouchTargets(
      await collectTouchTargets(coarsePage.locator("main.symbol-page")),
      1200,
      "symbol coarse pointer"
    );
  } finally {
    await coarseContext.close();
  }
});

test("dashboard and symbol routes reflow at a browser-equivalent 200% zoom layout", async ({
  browser
}) => {
  test.setTimeout(120_000);
  test.info().annotations.push({
    type: "zoom-model",
    description:
      "Playwright cannot drive browser-chrome zoom. CDP page scale is visual/pinch zoom and deviceScaleFactor alone changes raster density, not reflow. A 640 CSS px viewport at DPR 2 models the layout viewport of a 1280 physical px surface at 200% browser zoom."
  });

  const zoomContext = await browser.newContext({
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 640, height: 500 },
    deviceScaleFactor: 2
  });
  const zoomPage = await zoomContext.newPage();
  try {
    const zoomEnvironment = await zoomPage.evaluate(() => ({
      devicePixelRatio: window.devicePixelRatio,
      innerWidth: window.innerWidth
    }));
    expect(zoomEnvironment).toEqual({ devicePixelRatio: 2, innerWidth: 640 });

    await zoomPage.goto("/");
    await exposeHorizontalOverflow(zoomPage);
    const dashboardRoot = await measureRootOverflow(zoomPage);
    expect(dashboardRoot.overflowPx, `200% dashboard root: ${JSON.stringify(dashboardRoot)}`).toBe(0);
    await assertRegionsFitViewport(
      zoomPage,
      [
        ["terminal", zoomPage.locator("main.terminal")],
        ["topbar", zoomPage.locator(".topbar")],
        ["workspace", zoomPage.locator(".workspace")],
        ["watchlist", zoomPage.getByRole("region", { name: "精密監視リスト" })],
        ["detail", zoomPage.getByRole("complementary", { name: "選択銘柄の詳細" })]
      ],
      640,
      "200% dashboard"
    );
    await assertSingleLineActions(zoomPage, 640, "200% dashboard");
    const dashboardFocus = zoomPage.getByRole("button", { name: "service snapshotを更新" });
    await assertSemanticFocusRing(dashboardFocus, "200% dashboard refresh");
    await expect(dashboardFocus).toBeFocused();

    await zoomPage.goto("/symbols/ALTUSDT?tf=15m");
    await exposeHorizontalOverflow(zoomPage);
    const symbolRoot = await measureRootOverflow(zoomPage);
    expect(symbolRoot.overflowPx, `200% symbol root: ${JSON.stringify(symbolRoot)}`).toBe(0);
    await assertRegionsFitViewport(
      zoomPage,
      [
        ["page", zoomPage.locator("main.symbol-page")],
        ["top", zoomPage.locator(".symbol-top")],
        ["analysis", zoomPage.locator(".analysis-shell")],
        ["timeframes", zoomPage.getByRole("region", { name: "時間軸別データ" })],
        ["workspace", zoomPage.getByRole("region", { name: "補助情報" })]
      ],
      640,
      "200% symbol"
    );
    await assertSingleLineActions(zoomPage, 640, "200% symbol");
    const symbolFocus = zoomPage.getByRole("link", { name: "一覧へ" });
    await assertSemanticFocusRing(symbolFocus, "200% symbol back link");
    await expect(symbolFocus).toBeFocused();
  } finally {
    await zoomContext.close();
  }
});

test("market rows keep a stable 42px or 82px rhythm while exposing every signal", async ({
  page
}) => {
  test.setTimeout(120_000);
  const originalText = readFileSync(e2ePaths.snapshotPath, "utf-8");
  const originalPastNotesText = existsSync(pastNotesPath)
    ? readFileSync(pastNotesPath, "utf-8")
    : null;
  const originalTickerText = existsSync(e2ePaths.tickerRuntimePath)
    ? readFileSync(e2ePaths.tickerRuntimePath, "utf-8")
    : null;
  const snapshot = JSON.parse(originalText) as LayoutSnapshot;
  const rowBySymbol = new Map(snapshot.rows.map((row) => [row.symbol, row]));
  const zeroSignal = rowBySymbol.get("SLEEPUSDT");
  const oneSignal = rowBySymbol.get("ALTUSDT");
  const maxSignal = rowBySymbol.get("DUMPUSDT");
  if (!zeroSignal || !oneSignal || !maxSignal) throw new Error("row rhythm fixture symbols missing");

  Object.assign(zeroSignal, {
    changePctByTf: { "5m": 0, "15m": 0, "1h": 0, "24h": 0 },
    volumeRatioByTf: { "15m": 1 }
  });
  Object.assign(oneSignal, {
    changePctByTf: { "5m": 1, "15m": 0.5, "1h": 1.2, "24h": 3 },
    volumeRatioByTf: { "15m": 1 }
  });
  Object.assign(maxSignal, {
    changePctByTf: { "5m": -2.5, "15m": -1, "1h": -1.4, "24h": 3 },
    volumeRatioByTf: { "15m": 2.5 }
  });

  writeJsonAtomically(e2ePaths.snapshotPath, snapshot);
  writeJsonAtomically(pastNotesPath, {
    notes: [
      {
        symbol: "DUMPUSDT",
        reason: "行高確認",
        observedAt: "2026-07-18T00:00:00.000Z",
        expiresAt: "2027-07-18T00:00:00.000Z",
        note: "通常注記badgeの折返し確認"
      }
    ]
  });
  const freshTickerTs = Date.now() + 60_000;
  const freshTickerUpdate = ["DUMPUSDT", 98_765.4321, freshTickerTs] as const;
  writeJsonAtomically(e2ePaths.tickerRuntimePath, {
    schemaVersion: 1,
    sequence: 1,
    asOf: freshTickerTs,
    fullUpdates: [freshTickerUpdate],
    deltaUpdates: []
  });

  try {
    for (const width of [320, 375, 960, 1200, 1360, 1440]) {
      await test.step(`${width}px`, async () => {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/");
        const watchlist = page.getByRole("region", { name: "精密監視リスト" });
        const rowLocators = ["SLEEPUSDT", "ALTUSDT", "DUMPUSDT"].map((symbol) =>
          watchlist.locator(`[data-market-row][data-symbol="${symbol}"]`)
        );
        const rowBoxes = await Promise.all(rowLocators.map(measureElementBox));
        const watchlistBox = await measureElementBox(watchlist);
        const expectedHeight = watchlistBox.width >= 994 ? 42 : 82;
        const heights = rowBoxes.map((box) => box.height);
        expect(Math.max(...heights) - Math.min(...heights), `${width}px row heights ${heights}`).toBeLessThanOrEqual(2);
        for (const height of heights) {
          expect(height, `${width}px row height ${heights}`).toBeGreaterThanOrEqual(expectedHeight);
          expect(height, `${width}px row height ${heights}`).toBeLessThanOrEqual(expectedHeight + 2);
        }

        const zeroChips = rowLocators[0].locator(".signal-chip");
        const oneChips = rowLocators[1].locator(".signal-chip");
        const maxChips = rowLocators[2].locator(".signal-chip");
        await expect(zeroChips).toHaveCount(0);
        await expect(oneChips).toHaveCount(1);
        await expect(oneChips).toHaveText(["一致"]);
        await expect(oneChips).toHaveAttribute("aria-label", "5分/1時間一致");
        await expect(maxChips).toHaveCount(3);
        await expect(maxChips).toHaveText(["逆行", "急変", "量増"]);
        await expect(maxChips.nth(0)).toHaveAttribute("aria-label", "短期逆行");
        await expect(maxChips.nth(1)).toHaveAttribute("aria-label", "5分急変");
        await expect(maxChips.nth(2)).toHaveAttribute("aria-label", "出来高増");
        const maxRowButton = rowLocators[2].locator("[data-row-select]");
        await expect(maxRowButton).toHaveAttribute(
          "aria-label",
          /15m変化 .*15m代金 .*注記 銘柄注記.*短期逆行.*5分急変.*出来高増/
        );
        const priceDescriptionId = await maxRowButton.getAttribute("aria-describedby");
        expect(priceDescriptionId).toBeTruthy();
        await expect(rowLocators[2].locator(".current-price")).toHaveAttribute(
          "id",
          priceDescriptionId ?? ""
        );
        for (const locator of [
          rowLocators[2].locator(".symbol"),
          rowLocators[2].locator(".current-price"),
          rowLocators[2].locator(".volume-ratio"),
          rowLocators[2].locator(".note-badge"),
          rowLocators[2].locator(".tf-volume")
        ]) {
          await expect(locator).toBeVisible();
        }
        if (watchlistBox.width >= 994) {
          await expect(rowLocators[2].locator(".tf-metric")).toHaveCount(6);
          await expect(rowLocators[2].locator(".tf-metric").nth(1)).toBeVisible();
        } else {
          await expect(rowLocators[2].locator(".tf-change")).toBeVisible();
        }

        const signalGeometry = await maxChips.evaluateAll((chips) => {
          const label = chips[0]?.closest<HTMLElement>(".label");
          if (!label) throw new Error("signal label missing");
          const labelBox = label.getBoundingClientRect();
          return {
            label: { left: labelBox.left, right: labelBox.right },
            chips: chips.map((chip) => {
              const box = chip.getBoundingClientRect();
              const style = getComputedStyle(chip);
              return {
                left: box.left,
                right: box.right,
                top: box.top,
                bottom: box.bottom,
                clientWidth: chip.clientWidth,
                scrollWidth: chip.scrollWidth,
                visibility: style.visibility
              };
            })
          };
        });
        expect(
          Math.max(...signalGeometry.chips.map((box) => box.top)) -
            Math.min(...signalGeometry.chips.map((box) => box.top)),
          `${width}px signal wrap ${JSON.stringify(signalGeometry)}`
        ).toBeLessThanOrEqual(1);
        expect(
          signalGeometry.chips.every(
            (chip) =>
              chip.visibility === "visible" &&
              chip.left >= signalGeometry.label.left - 1 &&
              chip.right <= signalGeometry.label.right + 1 &&
              chip.scrollWidth <= chip.clientWidth
          ),
          `${width}px clipped signal ${JSON.stringify(signalGeometry)}`
        ).toBe(true);

        const noteGeometry = await rowLocators[2].locator(".note-badge").evaluate((badge) => {
          const row = badge.closest<HTMLElement>("[data-market-row]");
          if (!row) throw new Error("note row missing");
          const box = badge.getBoundingClientRect();
          const rowBox = row.getBoundingClientRect();
          return {
            top: box.top,
            bottom: box.bottom,
            left: box.left,
            right: box.right,
            rowTop: rowBox.top,
            rowBottom: rowBox.bottom,
            rowLeft: rowBox.left,
            rowRight: rowBox.right,
            clientHeight: badge.clientHeight,
            scrollHeight: badge.scrollHeight
          };
        });
        expect(noteGeometry.scrollHeight, `${width}px note wrap`).toBeLessThanOrEqual(
          noteGeometry.clientHeight
        );
        expect(noteGeometry.top, `${width}px note top`).toBeGreaterThanOrEqual(noteGeometry.rowTop - 1);
        expect(noteGeometry.bottom, `${width}px note bottom`).toBeLessThanOrEqual(
          noteGeometry.rowBottom + 1
        );
        expect(noteGeometry.left, `${width}px note left`).toBeGreaterThanOrEqual(noteGeometry.rowLeft - 1);
        expect(noteGeometry.right, `${width}px note right`).toBeLessThanOrEqual(
          noteGeometry.rowRight + 1
        );

        const beforeSelection = rowBoxes[2].height;
        await expect(maxRowButton).toHaveAttribute("aria-pressed", "false");
        await maxRowButton.focus();
        const focusedBox = await measureElementBox(rowLocators[2]);
        const focusedLayout = await rowLocators[2].evaluate((element) => {
          const row = element.getBoundingClientRect();
          return {
            row: { top: row.top, bottom: row.bottom, height: row.height },
            fields: Array.from(element.querySelectorAll<HTMLElement>("[data-row-select] > span")).map(
              (field) => {
                const box = field.getBoundingClientRect();
                return {
                  className: field.className,
                  text: field.textContent?.replace(/\s+/g, " ").trim(),
                  top: box.top,
                  bottom: box.bottom,
                  height: box.height,
                  clientHeight: field.clientHeight,
                  scrollHeight: field.scrollHeight
                };
              }
            )
          };
        });
        expect(
          Math.abs(focusedBox.height - beforeSelection),
          `${width}px focused height ${JSON.stringify(focusedLayout)}`
        ).toBeLessThanOrEqual(1);
        await maxRowButton.click();
        await expect(maxRowButton).toHaveAttribute("aria-pressed", "true");
        const selectedBox = await measureElementBox(rowLocators[2]);
        expect(Math.abs(selectedBox.height - beforeSelection), `${width}px selected height`).toBeLessThanOrEqual(1);

        if (width === 320) {
          const staleTickerTs = Date.now() - 6_000;
          const staleTickerUpdate = ["DUMPUSDT", 0.003575, staleTickerTs] as const;
          writeJsonAtomically(e2ePaths.tickerRuntimePath, {
            schemaVersion: 1,
            sequence: 2,
            asOf: staleTickerTs,
            fullUpdates: [staleTickerUpdate],
            deltaUpdates: [staleTickerUpdate]
          });
          await expect(rowLocators[2].locator(".current-price > span")).toHaveText("0.003575");
          await expect(rowLocators[2].locator(".current-price small")).toHaveText("STALE");
          const staleBox = await measureElementBox(rowLocators[2]);
          expect(Math.abs(staleBox.height - beforeSelection), "320px stale height").toBeLessThanOrEqual(1);
        }
      });
    }

    await page.addInitScript(() => {
      const installTextScale = () => {
        if (!document.head || document.querySelector("style[data-row-text-scale]")) return false;
        const style = document.createElement("style");
        style.dataset.rowTextScale = "2";
        style.textContent = `
          [data-row-select] :where(.symbol, .label, .volume-ratio, .tf-change, .tf-volume) {
            font-size: 28px !important;
            line-height: 1.4 !important;
          }
          [data-row-select] .current-price { font-size: 24px !important; line-height: 1.4 !important; }
          [data-row-select] .current-price small { font-size: 16px !important; line-height: 1.2 !important; }
          [data-row-select] .signal-chip { font-size: 20px !important; line-height: 1.2 !important; }
          [data-row-select] :where(.ok, .risk) { font-size: 22px !important; line-height: 1.2 !important; }
          [data-row-select] .note-badge { font-size: 20px !important; line-height: 1.2 !important; }
          [data-row-select] .tf-metric { font-size: 26px !important; line-height: 1.2 !important; }
        `;
        document.head.append(style);
        return true;
      };
      if (!installTextScale()) {
        const observer = new MutationObserver(() => {
          if (!installTextScale()) return;
          observer.disconnect();
        });
        observer.observe(document, { childList: true, subtree: true });
      }
    });
    await page.setViewportSize({ width: 375, height: 900 });
    await page.goto("/");
    const zoomRow = page.locator('[data-market-row][data-symbol="DUMPUSDT"]');
    await zoomRow.scrollIntoViewIfNeeded();
    await zoomRow.locator("[data-row-select]").focus();
    const zoomGeometry = await zoomRow.evaluate((element) => {
      const row = element.getBoundingClientRect();
      const label = element.querySelector<HTMLElement>(".label")?.getBoundingClientRect();
      if (!label) throw new Error("zoom signal label missing");
      const chips = Array.from(element.querySelectorAll<HTMLElement>(".signal-chip")).map((chip) => {
        const box = chip.getBoundingClientRect();
        return {
          left: box.left,
          right: box.right,
          top: box.top,
          bottom: box.bottom,
          clientWidth: chip.clientWidth,
          scrollWidth: chip.scrollWidth
        };
      });
      const visibleFields = Array.from(
        element.querySelectorAll<HTMLElement>(
          ".symbol, .current-price, .label, .volume-ratio, .tf-change, .tf-volume, .ok, .risk, .note-badge"
        )
      ).flatMap((field) => {
        const style = getComputedStyle(field);
        if (style.display === "none" || style.visibility === "hidden") return [];
        const box = field.getBoundingClientRect();
        return [{ selector: field.className, left: box.left, right: box.right, top: box.top, bottom: box.bottom }];
      });
      const textFields = Array.from(
        element.querySelectorAll<HTMLElement>(
          ".symbol, .current-price > span, .current-price small, .label > span:first-child, .signal-chip, .volume-ratio, .tf-change, .tf-volume, .ok, .risk:not(.tf-metric), .note-badge"
        )
      ).flatMap((field) => {
        const style = getComputedStyle(field);
        if (style.display === "none" || style.visibility === "hidden") return [];
        const box = field.getBoundingClientRect();
        return [
          {
            selector: field.className,
            left: box.left,
            right: box.right,
            top: box.top,
            bottom: box.bottom,
            clientWidth: field.clientWidth,
            scrollWidth: field.scrollWidth,
            clientHeight: field.clientHeight,
            scrollHeight: field.scrollHeight,
            recoveryText:
              field.getAttribute("title") ??
              field.closest<HTMLElement>("[title]")?.getAttribute("title") ??
              field.getAttribute("aria-label")
          }
        ];
      });
      return {
        row: { left: row.left, right: row.right, top: row.top, bottom: row.bottom, height: row.height },
        label: { left: label.left, right: label.right, top: label.top, bottom: label.bottom },
        chips,
        visibleFields,
        textFields
      };
    });
    expect(zoomGeometry.chips).toHaveLength(3);
    expect(zoomGeometry.row.height, JSON.stringify(zoomGeometry)).toBeGreaterThan(82);
    expect(
      zoomGeometry.chips.every(
        (chip) =>
          chip.left >= zoomGeometry.label.left - 1 &&
          chip.right <= zoomGeometry.label.right + 1 &&
          chip.top >= zoomGeometry.row.top - 1 &&
          chip.bottom <= zoomGeometry.row.bottom + 1 &&
          chip.scrollWidth <= chip.clientWidth
      ),
      JSON.stringify(zoomGeometry)
    ).toBe(true);
    expect(
      zoomGeometry.visibleFields.every(
        (field) =>
          field.left >= zoomGeometry.row.left - 1 &&
          field.right <= zoomGeometry.row.right + 1 &&
          field.top >= zoomGeometry.row.top - 1 &&
          field.bottom <= zoomGeometry.row.bottom + 1
      ),
      JSON.stringify(zoomGeometry)
    ).toBe(true);
    expect(
      zoomGeometry.textFields.every(
        (field) =>
          field.left >= zoomGeometry.row.left - 1 &&
          field.right <= zoomGeometry.row.right + 1 &&
          field.top >= zoomGeometry.row.top - 1 &&
          field.bottom <= zoomGeometry.row.bottom + 1 &&
          ((field.scrollWidth <= field.clientWidth + 1 &&
            field.scrollHeight <= field.clientHeight + 1) ||
            Boolean(field.recoveryText))
      ),
      JSON.stringify(zoomGeometry)
    ).toBe(true);
  } finally {
    writeFileSync(e2ePaths.snapshotPath, originalText, "utf-8");
    if (originalPastNotesText === null) {
      rmSync(e2ePaths.pastNotesDir, { recursive: true, force: true });
    } else {
      writeFileSync(pastNotesPath, originalPastNotesText, "utf-8");
    }
    if (originalTickerText === null) {
      rmSync(e2ePaths.tickerRuntimePath, { force: true });
    } else {
      writeFileSync(e2ePaths.tickerRuntimePath, originalTickerText, "utf-8");
    }
  }
});

test("production surfaces do not mask horizontal overflow with clip", async ({ page }) => {
  await page.goto("/");
  const dashboardOverflow = await page.evaluate(() => ({
    html: getComputedStyle(document.documentElement).overflowX,
    body: getComputedStyle(document.body).overflowX
  }));
  expect(dashboardOverflow).toEqual({ html: "visible", body: "visible" });

  await page.goto("/symbols/ALTUSDT?tf=15m");
  const symbolOverflow = await page.evaluate(() => {
    const workspace = document.querySelector<HTMLElement>(".intel-grid");
    if (!workspace) throw new Error("symbol workspace missing");
    return {
      html: getComputedStyle(document.documentElement).overflowX,
      body: getComputedStyle(document.body).overflowX,
      workspace: getComputedStyle(workspace).overflowX
    };
  });
  expect(symbolOverflow).toEqual({ html: "visible", body: "visible", workspace: "visible" });
});

test("symbol route keeps major regions bounded from 320px through 1920px without clipping", async ({
  page
}) => {
  test.setTimeout(120_000);
  const widths = [320, 375, 414, 768, 960, 1200, 1360, 1440, 1920];
  for (const width of widths) {
    await test.step(`${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/symbols/ALTUSDT?tf=15m");
      await exposeHorizontalOverflow(page);

      const visibleOverflow = await page.evaluate(() => {
        const workspace = document.querySelector<HTMLElement>(".intel-grid");
        if (!workspace) throw new Error("symbol workspace missing");
        return {
          html: getComputedStyle(document.documentElement).overflowX,
          body: getComputedStyle(document.body).overflowX,
          workspace: getComputedStyle(workspace).overflowX
        };
      });
      expect(visibleOverflow, `${width}px overflow visibility probe`).toEqual({
        html: "visible",
        body: "visible",
        workspace: "visible"
      });

      const root = await measureRootOverflow(page);
      expect(root.overflowPx, `${width}px symbol root: ${JSON.stringify(root)}`).toBe(0);
      await assertRegionsFitViewport(
        page,
        [
          ["page", page.locator("main.symbol-page")],
          ["top", page.locator(".symbol-top")],
          ["analysis", page.locator(".analysis-shell")],
          ["timeframes", page.getByRole("region", { name: "時間軸別データ" })],
          ["workspace", page.getByRole("region", { name: "補助情報" })]
        ],
        width,
        "symbol"
      );
    });
  }
});

test("intermediate dashboard widths do not overflow and keep topbar edges aligned", async ({
  page
}) => {
  const widths = [
    320, 375, 414, 768, 960, 961, 1024, 1080, 1176, 1199, 1200, 1280, 1359, 1360,
    1361, 1440, 1920
  ];
  for (const width of widths) {
    await test.step(`${width}px`, async () => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/");
      await exposeHorizontalOverflow(page);

      const root = await measureRootOverflow(page);
      const watchlist = await measureElementOverflow(
        page.getByRole("region", { name: "精密監視リスト" })
      );
      const watchlistBox = await measureElementBox(
        page.getByRole("region", { name: "精密監視リスト" })
      );
      const topbar = await measureElementBox(page.locator(".topbar"));
      const workspace = await measureElementBox(page.locator(".workspace"));
      const detail = await measureElementBox(
        page.getByRole("complementary", { name: "選択銘柄の詳細" })
      );
      const layout = await page.evaluate(() => {
        const watchlist = document.querySelector<HTMLElement>('[aria-label="精密監視リスト"]');
        const header = watchlist?.querySelector<HTMLElement>(".market-header");
        const workspace = document.querySelector<HTMLElement>(".workspace");
        if (!watchlist || !header || !workspace) throw new Error("dashboard layout node missing");
        return {
          containerType: getComputedStyle(watchlist).containerType,
          headerDisplay: getComputedStyle(header).display,
          workspaceDisplay: getComputedStyle(workspace).display
        };
      });
      const overflowers = await page.evaluate(() =>
        Array.from(document.querySelectorAll<HTMLElement>("body *"))
          .flatMap((element) => {
            const box = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            if (
              box.width === 0 ||
              box.height === 0 ||
              style.position === "fixed" ||
              box.left >= -0.5 && box.right <= window.innerWidth + 0.5
            ) {
              return [];
            }
            return [
              {
                tag: element.tagName.toLowerCase(),
                className: element.className,
                left: box.left,
                right: box.right,
                width: box.width,
                text: element.textContent?.replace(/\s+/g, " ").trim().slice(0, 80) ?? ""
              }
            ];
          })
          .slice(0, 12)
      );

      expect(
        root.overflowPx,
        `${width}px root: ${JSON.stringify(root)} overflowers=${JSON.stringify(overflowers)}`
      ).toBe(0);
      expect(watchlist.overflowPx, `${width}px watchlist: ${JSON.stringify(watchlist)}`).toBe(0);
      expect(Math.abs(topbar.x - workspace.x), `${width}px left edge`).toBeLessThanOrEqual(1);
      expect(
        Math.abs(topbar.x + topbar.width - (workspace.x + workspace.width)),
        `${width}px right edge`
      ).toBeLessThanOrEqual(1);
      expect(layout.containerType, `${width}px watchlist container`).toBe("inline-size");
      expect(layout.headerDisplay === "grid", `${width}px table/card representation`).toBe(
        watchlist.clientWidth >= 994
      );
      expect(detail.x, `${width}px detail left`).toBeGreaterThanOrEqual(0);
      expect(detail.x + detail.width, `${width}px detail right`).toBeLessThanOrEqual(width);
      if (width >= 1360) {
        expect(layout.workspaceDisplay).toBe("grid");
        expect(detail.width, `${width}px detail width`).toBeGreaterThanOrEqual(300);
        expect(watchlist.clientWidth, `${width}px watchlist width`).toBeGreaterThanOrEqual(994);
        expect(detail.x, `${width}px detail follows watchlist`).toBeGreaterThan(
          watchlistBox.x + watchlistBox.width
        );
      } else {
        expect(Math.abs(detail.x - workspace.x), `${width}px one-column detail left`).toBeLessThanOrEqual(
          1
        );
        expect(
          Math.abs(detail.width - workspace.width),
          `${width}px one-column detail width`
        ).toBeLessThanOrEqual(1);
      }
    });
  }
});

test("mobile keeps all ranking links and 400 rows reachable before the selected detail", async ({
  page
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const basicDocumentHeight = await page.evaluate(() => document.documentElement.scrollHeight);

  const originalText = readFileSync(e2ePaths.snapshotPath, "utf-8");
  const snapshot = JSON.parse(originalText) as LayoutSnapshot;
  const basicSymbols = new Set([
    "ALTUSDT",
    "NEWALTUSDT",
    "DUMPUSDT",
    "THINUSDT",
    "SLEEPUSDT"
  ]);
  const basicRows = snapshot.rows.filter((row) => basicSymbols.has(row.symbol));
  if (basicRows.length !== 5) throw new Error(`basic fixture row count changed: ${basicRows.length}`);
  const base = basicRows.find((row) => row.symbol === "SLEEPUSDT");
  if (!base) throw new Error("basic fixture SLEEPUSDT row is missing");
  const addedRows = Array.from({ length: 395 }, (_, index): LayoutSnapshotRow => ({
    ...structuredClone(base),
    symbol: `LAYOUT${String(index + 1).padStart(4, "0")}USDT`
  }));
  snapshot.rows = [...basicRows, ...addedRows];
  snapshot.summary.counts = {
    WATCH: 2,
    CAUTION: 1,
    NO_TRADE: 1,
    LOW_PRIORITY: 1 + addedRows.length
  };

  const metricIds = ["changeUp", "changeDown", "turnoverTop", "volumeUp"] as const;
  for (const [metricIndex, metric] of metricIds.entries()) {
    snapshot.rankings.timeframes["15m"][metric] = Array.from({ length: 10 }, (_, index) => ({
      symbol: `RANK${metricIndex + 1}${String(index + 1).padStart(2, "0")}USDT`,
      value: metric === "changeDown" ? -(index + 1) : (metricIndex + 1) * 100 + index
    }));
    snapshot.rankings.meta.timeframes["15m"][metric].limit = 10;
    snapshot.rankings.meta.timeframes["15m"][metric].totalEligible = 10;
  }

  writeJsonAtomically(e2ePaths.snapshotPath, snapshot);
  try {
    await page.reload();

    const sections = await page
      .locator("[data-dashboard-section]")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-dashboard-section")));
    expect(sections).toEqual([
      "candidate",
      "watchlist",
      "detail",
      "smart-rank"
    ]);

    const rankingBody = page.locator('[data-dashboard-section="candidate"] .mobile-rankings');
    const rows = page.locator(
      '[data-dashboard-section="watchlist"] [data-market-row][data-symbol]'
    );
    await expect(rankingBody.locator(".rank-panel")).toHaveCount(4);
    await expect(rankingBody.locator("a.rank-row")).toHaveCount(40);
    await expect(rows).toHaveCount(400);

    const geometry = await page.evaluate(() => {
      const ranking = document.querySelector<HTMLElement>(".mobile-rankings");
      const rows = document.querySelector<HTMLElement>('[aria-label="精密監視リスト"] .rows');
      const detail = document.querySelector<HTMLElement>('[data-dashboard-section="detail"]');
      if (!ranking || !rows || !detail) throw new Error("bounded mobile section missing");
      return {
        documentHeight: document.documentElement.scrollHeight,
        detailTop: detail.getBoundingClientRect().top + window.scrollY,
        rankingClientHeight: ranking.clientHeight,
        rankingScrollHeight: ranking.scrollHeight,
        rowsClientHeight: rows.clientHeight,
        rowsScrollHeight: rows.scrollHeight,
        rankingOverscroll: getComputedStyle(ranking).overscrollBehaviorY,
        rankingTouchAction: getComputedStyle(ranking).touchAction,
        rowsOverscroll: getComputedStyle(rows).overscrollBehaviorY,
        rowsTouchAction: getComputedStyle(rows).touchAction
      };
    });
    expect(geometry.documentHeight - basicDocumentHeight).toBeLessThan(844);
    expect(geometry.detailTop).toBeLessThanOrEqual(844 * 4);
    expect(geometry.rankingScrollHeight).toBeGreaterThan(geometry.rankingClientHeight);
    expect(geometry.rowsScrollHeight).toBeGreaterThan(geometry.rowsClientHeight);
    expect(geometry.rankingOverscroll).toBe("auto");
    expect(geometry.rankingTouchAction).toContain("pan-y");
    expect(geometry.rowsOverscroll).toBe("auto");
    expect(geometry.rowsTouchAction).toContain("pan-y");

    const activeRankingLinks = rankingBody.getByRole("tabpanel").locator("a.rank-row");
    await activeRankingLinks.last().scrollIntoViewIfNeeded();
    await expect(activeRankingLinks.last()).toBeVisible();
    await rows.last().locator("[data-row-select]").scrollIntoViewIfNeeded();
    await expect(rows.last()).toBeVisible();

    const rowTabStop = page.locator('[data-row-select][tabindex="0"]');
    await rowTabStop.focus();
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toHaveAttribute(
      "aria-label",
      "THINUSDT の個別分析を開く"
    );

    const rowsScroller = page.locator('[aria-label="精密監視リスト"] .rows');
    await rowsScroller.evaluate((element) => {
      element.scrollTop = Math.min(800, element.scrollHeight - element.clientHeight);
    });
    await expect.poll(() => rowsScroller.evaluate((element) => element.scrollTop)).toBeGreaterThan(0);
    await page
      .getByRole("complementary", { name: "分類" })
      .getByRole("button", { name: /低優先\s+396/ })
      .click();
    await expect.poll(() => rowsScroller.evaluate((element) => element.scrollTop)).toBe(0);
  } finally {
    writeFileSync(e2ePaths.snapshotPath, originalText, "utf-8");
  }
});
