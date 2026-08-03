import { defineConfig, devices } from "@playwright/test";
import {
  resolveWebTestStatePaths,
  shellEnvironment
} from "./test-state-paths";

const e2ePaths = resolveWebTestStatePaths("e2e");
const e2eStateEnv = shellEnvironment({
  PREP_WATCHDECK_STATE_DIR: e2ePaths.runtimeRoot
});
const cleanupEnv = shellEnvironment({
  WATCHDECK_TEST_RUNTIME_ROOT: e2ePaths.runtimeRoot
});

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: "**/*.e2e.ts",
  outputDir: e2ePaths.playwrightOutputDir,
  workers: 1,
  timeout: 30_000,
  expect: {
    timeout: 5_000
  },
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "on-first-retry"
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
      `cd ../scanner-core && ${e2eStateEnv} uv run watchdeck scan --source fixture --fixture-set basic --template balanced`,
      "cd ../web && bun run build",
      `${e2eStateEnv} bun run preview -- --port 4173`
    ].join(" && "),
    url: "http://127.0.0.1:4173/",
    reuseExistingServer: false,
    timeout: 120_000
  }
});
