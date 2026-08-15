import { resolve } from "node:path";
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "**/*.e2e.ts",
  outputDir: resolve(process.cwd(), "../../var/tmp/e2e/playwright-results"),
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  use: {
    baseURL: "http://127.0.0.1:4174",
    channel: process.env.CI ? undefined : "chrome",
    screenshot: "only-on-failure",
    trace: "on-first-retry"
  },
  projects: [
    {
      name: "desktop-1440",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } }
    },
    {
      name: "mobile-390",
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } }
    }
  ],
  webServer: {
    command: "bun run build && bun run preview -- --port 4174 --strictPort",
    env: {
      PREP_WATCHDECK_MARKET_STATE_DIR: resolve(
        process.cwd(),
        "../../var/tmp/e2e/runtime"
      )
    },
    url: "http://127.0.0.1:4174/api/health",
    reuseExistingServer: false,
    timeout: 120_000
  }
});
