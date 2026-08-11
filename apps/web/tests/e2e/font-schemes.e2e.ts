import { expect, test, type Page } from "@playwright/test";

const storageKey = "prep-watchdeck:font-scheme";
const fontCases = [
  { id: "watchdeck", label: "標準（コンパクト）", family: "Watchdeck Sans" },
  { id: "terminal", label: "等幅（ターミナル）", family: "Cascadia Mono" }
] as const;

async function readFont(page: Page) {
  return page.evaluate(() => {
    const rootStyle = getComputedStyle(document.documentElement);
    const bodyStyle = getComputedStyle(document.body);
    return {
      id: document.documentElement.getAttribute("data-font-scheme"),
      saved: localStorage.getItem("prep-watchdeck:font-scheme"),
      token: rootStyle.getPropertyValue("--font-sans").trim(),
      body: bodyStyle.fontFamily
    };
  });
}

test("both routes expose compact and monospace font choices", async ({ page }) => {
  for (const route of ["/", "/symbols/ALTUSDT?tf=15m"]) {
    await page.goto(route);
    const selector = page.getByLabel("フォント");
    await expect(selector).toBeVisible();
    await expect(selector.locator("option")).toHaveText(fontCases.map((font) => font.label));

    for (const font of fontCases) {
      await selector.selectOption(font.id);
      await expect(selector).toHaveValue(font.id);
      await expect.poll(() => readFont(page)).toMatchObject({ id: font.id, saved: font.id });
      const applied = await readFont(page);
      expect(applied.token).toContain(font.family);
      expect(applied.body).toContain(font.family);
    }
  }
});

test("font selection survives navigation and reload while invalid storage fails closed", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("フォント").selectOption("terminal");

  await page.goto("/symbols/ALTUSDT?tf=15m");
  await expect(page.getByLabel("フォント")).toHaveValue("terminal");
  expect(await readFont(page)).toMatchObject({ id: "terminal", saved: "terminal" });

  await page.reload();
  await expect(page.getByLabel("フォント")).toHaveValue("terminal");
  expect(await readFont(page)).toMatchObject({ id: "terminal", saved: "terminal" });

  await page.evaluate((key) => localStorage.setItem(key, "readable"), storageKey);
  await page.reload();
  await expect(page.getByLabel("フォント")).toHaveValue("watchdeck");
  expect(await readFont(page)).toMatchObject({ id: "watchdeck", saved: "readable" });
});

test("font changes do not recreate the chart, observer, or request", async ({ page }) => {
  await page.addInitScript(() => {
    const lifecycle = { created: 0, removed: 0, observerCreated: 0, observerDisconnected: 0 };
    const instrumentedWindow = window as Window &
      typeof globalThis & {
        __watchdeckFontLifecycle?: typeof lifecycle;
        __watchdeckInstrumentation?: {
          chartCreated: () => void;
          chartRemoved: () => void;
          chartResizeObserverCreated: () => void;
          chartResizeObserverDisconnected: () => void;
        };
      };
    instrumentedWindow.__watchdeckFontLifecycle = lifecycle;
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
        (window as Window & { __watchdeckFontLifecycle?: { created: number } })
          .__watchdeckFontLifecycle?.created ?? 0
      )
    )
    .toBe(1);
  const requestsBeforeFontChange = chartRequests;

  for (const id of ["terminal", "watchdeck"] as const) {
    await page.getByLabel("フォント").selectOption(id);
    await expect(page.locator("html")).toHaveAttribute("data-font-scheme", id);
  }

  const lifecycle = await page.evaluate(
    () =>
      (window as Window & {
        __watchdeckFontLifecycle?: {
          created: number;
          removed: number;
          observerCreated: number;
          observerDisconnected: number;
        };
      }).__watchdeckFontLifecycle
  );
  expect(lifecycle).toEqual({ created: 1, removed: 0, observerCreated: 1, observerDisconnected: 0 });
  expect(chartRequests).toBe(requestsBeforeFontChange);
});

test("font selector stays bounded and touch-sized across route widths", async ({ page }) => {
  for (const route of ["/", "/symbols/ALTUSDT?tf=15m"]) {
    for (const width of [320, 560, 1440, 1920]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(route);
      const selector = page.getByLabel("フォント");
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
