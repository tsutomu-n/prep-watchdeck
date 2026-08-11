import { expect, test, type Page } from "@playwright/test";

const storageKey = "prep-watchdeck:color-scheme";
const themeCases = [
  {
    id: "watchdeck",
    label: "標準",
    mode: "dark",
    tokens: { bg: "#070908", text: "#f3f5ed", focus: "#d8ff38", colorScheme: "dark" }
  },
  {
    id: "carbon-aurora",
    label: "Carbon Aurora",
    mode: "dark",
    tokens: { bg: "#0b0d10", text: "#f4f7fa", focus: "#33b1ff", colorScheme: "dark" }
  },
  {
    id: "forest-amber",
    label: "Forest Amber",
    mode: "dark",
    tokens: { bg: "#1e2326", text: "#d3c6aa", focus: "#dbbc7f", colorScheme: "dark" }
  },
  {
    id: "plum-signal",
    label: "Plum Signal",
    mode: "dark",
    tokens: { bg: "#141421", text: "#f8f8f2", focus: "#ab9df2", colorScheme: "dark" }
  },
  {
    id: "paper-ledger",
    label: "Paper Ledger",
    mode: "light",
    tokens: { bg: "#f3ead3", text: "#26313a", focus: "#1e6fcc", colorScheme: "light" }
  },
  {
    id: "arctic-terminal",
    label: "Arctic Terminal",
    mode: "light",
    tokens: { bg: "#f3f5f7", text: "#202124", focus: "#1967d2", colorScheme: "light" }
  },
  {
    id: "sage-field",
    label: "Sage Field",
    mode: "light",
    tokens: { bg: "#eef1e8", text: "#24333a", focus: "#2b6e9e", colorScheme: "light" }
  },
  {
    id: "lilac-current",
    label: "Lilac Current",
    mode: "light",
    tokens: { bg: "#f4f1f8", text: "#2d2933", focus: "#6d46b8", colorScheme: "light" }
  }
] as const;

async function readTheme(page: Page) {
  return page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return {
      id: document.documentElement.getAttribute("data-color-scheme"),
      saved: localStorage.getItem("prep-watchdeck:color-scheme"),
      bg: style.getPropertyValue("--bg").trim(),
      text: style.getPropertyValue("--text").trim(),
      focus: style.getPropertyValue("--focus").trim(),
      colorScheme: style.colorScheme
    };
  });
}

test("both routes expose the eight semantic color schemes", async ({ page }) => {
  for (const route of ["/", "/symbols/ALTUSDT?tf=15m"]) {
    await page.goto(route);
    const selector = page.getByLabel("配色");
    await expect(selector).toBeVisible();
    await expect(selector.locator("option")).toHaveCount(themeCases.length);
    await expect(selector.locator("option")).toHaveText(themeCases.map((theme) => theme.label));
    const groups = selector.locator("optgroup");
    await expect(groups).toHaveCount(2);
    await expect(groups.nth(0)).toHaveAttribute("label", "ダークテーマ");
    await expect(groups.nth(1)).toHaveAttribute("label", "ライトテーマ");
    await expect(selector.locator('optgroup[label="ダークテーマ"] option')).toHaveCount(4);
    await expect(selector.locator('optgroup[label="ライトテーマ"] option')).toHaveCount(4);

    for (const theme of themeCases) {
      await selector.selectOption(theme.id);
      await expect(selector).toHaveValue(theme.id);
      await expect(
        page.getByLabel(`現在のテーマ種別: ${theme.mode === "dark" ? "ダーク" : "ライト"}`)
      ).toHaveText(theme.mode.toUpperCase());
      await expect
        .poll(() => readTheme(page))
        .toEqual({ id: theme.id, saved: theme.id, ...theme.tokens });
    }
  }
});

test("selection survives navigation and reload while invalid storage fails closed", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("配色").selectOption("paper-ledger");

  await page.goto("/symbols/ALTUSDT?tf=15m");
  await expect(page.getByLabel("配色")).toHaveValue("paper-ledger");
  expect(await readTheme(page)).toMatchObject({
    id: "paper-ledger",
    saved: "paper-ledger",
    colorScheme: "light"
  });

  await page.reload();
  await expect(page.getByLabel("配色")).toHaveValue("paper-ledger");
  expect(await readTheme(page)).toMatchObject({
    id: "paper-ledger",
    saved: "paper-ledger",
    colorScheme: "light"
  });

  await page.evaluate((key) => localStorage.setItem(key, "unknown-theme"), storageKey);
  await page.reload();
  await expect(page.getByLabel("配色")).toHaveValue("watchdeck");
  expect(await readTheme(page)).toMatchObject({ id: "watchdeck", saved: "unknown-theme" });
});

test("chart recolors without chart, observer, or request lifecycle churn", async ({ page }) => {
  await page.addInitScript(() => {
    const lifecycle = { created: 0, removed: 0, observerCreated: 0, observerDisconnected: 0 };
    const instrumentedWindow = window as Window &
      typeof globalThis & {
        __watchdeckThemeLifecycle?: typeof lifecycle;
        __watchdeckInstrumentation?: {
          chartCreated: () => void;
          chartRemoved: () => void;
          chartResizeObserverCreated: () => void;
          chartResizeObserverDisconnected: () => void;
        };
      };
    instrumentedWindow.__watchdeckThemeLifecycle = lifecycle;
    instrumentedWindow.__watchdeckInstrumentation = {
      chartCreated: () => lifecycle.created += 1,
      chartRemoved: () => lifecycle.removed += 1,
      chartResizeObserverCreated: () => lifecycle.observerCreated += 1,
      chartResizeObserverDisconnected: () => lifecycle.observerDisconnected += 1
    };
  });

  let chartRequests = 0;
  page.on("request", (request) => {
    if (/\/api\/symbols\/ALTUSDT\/chart\?/.test(request.url())) chartRequests += 1;
  });

  await page.goto("/symbols/ALTUSDT?tf=15m");
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as Window & { __watchdeckThemeLifecycle?: { created: number } })
          .__watchdeckThemeLifecycle?.created ?? 0
      )
    )
    .toBe(1);
  const requestsBeforeThemeChange = chartRequests;

  for (const id of [
    "carbon-aurora",
    "forest-amber",
    "plum-signal",
    "paper-ledger",
    "arctic-terminal",
    "sage-field",
    "lilac-current"
  ] as const) {
    await page.getByLabel("配色").selectOption(id);
    await expect(page.locator("html")).toHaveAttribute("data-color-scheme", id);
  }
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  const lifecycle = await page.evaluate(
    () =>
      (window as Window & {
        __watchdeckThemeLifecycle?: {
          created: number;
          removed: number;
          observerCreated: number;
          observerDisconnected: number;
        };
      }).__watchdeckThemeLifecycle
  );
  expect(lifecycle).toEqual({ created: 1, removed: 0, observerCreated: 1, observerDisconnected: 0 });
  expect(chartRequests).toBe(requestsBeforeThemeChange);
});

test("theme selector stays bounded and touch-sized across route widths", async ({ page }) => {
  for (const route of ["/", "/symbols/ALTUSDT?tf=15m"]) {
    for (const width of [320, 560, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route);
      const selector = page.getByLabel("配色");
      const box = await selector.boundingBox();
      expect(box, `${route} ${width}px selector box`).not.toBeNull();
      expect(box!.x, `${route} ${width}px left`).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${route} ${width}px right`).toBeLessThanOrEqual(width);
      expect(box!.height, `${route} ${width}px target height`).toBeGreaterThanOrEqual(
        width <= 768 ? 44 : 34
      );
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
        `${route} ${width}px root overflow`
      ).toBe(0);
    }
  }
});
