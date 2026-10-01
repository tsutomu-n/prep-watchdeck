import { resolve } from "node:path";
import { realpathSync } from "node:fs";
import { defineConfig, devices } from "@playwright/test";

const state = process.env.PREP_WATCHDECK_PERSONA_STATE_DIR;
if (!state || !realpathSync(state).startsWith("/tmp/prep-watchdeck-persona-")) {
  throw new Error("PREP_WATCHDECK_PERSONA_STATE_DIR must name a dedicated /tmp persona state");
}
const rankingPort = process.env.PREP_WATCHDECK_PERSONA_RANKING_PORT;
if (!rankingPort || !/^\d+$/.test(rankingPort) || Number(rankingPort) < 1024
  || Number(rankingPort) > 65535 || [5173, 5432, 55432, 8769].includes(Number(rankingPort))) {
  throw new Error("Use an explicit isolated ranking API port");
}

export default defineConfig({
  testDir: "./tests/acceptance",
  testMatch: "**/*.e2e.ts",
  outputDir: resolve(state, "../browser"),
  reporter: [["list"], ["json", { outputFile: resolve(state, "../browser-results.json") }]],
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: "http://127.0.0.1:4178", channel: "chrome",
    actionTimeout: 15_000, navigationTimeout: 20_000,
    screenshot: "on", trace: "on"
  },
  projects: [
    { name: "desktop-1440", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 960 } } },
    { name: "mobile-390", use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } } }
  ],
  webServer: {
    command: "bun run preview -- --port 4178 --strictPort",
    env: {
      PREP_WATCHDECK_MARKET_STATE_DIR: resolve(state),
      PREP_WATCHDECK_RANKING_PORT: rankingPort
    },
    url: "http://127.0.0.1:4178/api/health", reuseExistingServer: false, timeout: 60_000
  }
});
