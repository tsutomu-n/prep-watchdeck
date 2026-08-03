import { defineConfig, devices } from "@playwright/test";
import {
  resolveWebTestStatePaths,
  shellEnvironment
} from "./test-state-paths";

const performancePaths = resolveWebTestStatePaths("performance");
const performanceStateEnv = shellEnvironment({
  PREP_WATCHDECK_STATE_DIR: performancePaths.runtimeRoot
});
const cleanupEnv = shellEnvironment({
  WATCHDECK_TEST_RUNTIME_ROOT: performancePaths.runtimeRoot
});

export default defineConfig({
  testDir: "./tests/performance",
  testMatch: "**/*.performance.ts",
  outputDir: performancePaths.playwrightOutputDir,
  workers: 1,
  timeout: 150_000,
  expect: {
    timeout: 10_000
  },
  use: {
    baseURL: "http://127.0.0.1:4174",
    trace: "off"
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ],
  webServer: {
    command: [
      `cd ../web && ${cleanupEnv} bun -e 'import { rmSync } from "node:fs"; rmSync(process.env.WATCHDECK_TEST_RUNTIME_ROOT, { recursive: true, force: true })'`,
      `cd ../scanner-core && ${performanceStateEnv} uv run watchdeck scan --source fixture --fixture-set basic --template balanced`,
      "cd ../web && bun run build",
      `${performanceStateEnv} bun run preview -- --port 4174`
    ].join(" && "),
    url: "http://127.0.0.1:4174/",
    reuseExistingServer: false,
    timeout: 120_000
  }
});
