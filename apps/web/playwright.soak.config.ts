import { defineConfig } from "@playwright/test";
import {
  resolveWebTestStatePaths,
  shellEnvironment
} from "./test-state-paths";

const soakDurationMs = positiveInteger(process.env.SOAK_DURATION_MS, 3_600_000);
const soakPort = positiveInteger(process.env.SOAK_PORT, 4_175);
const soakPaths = resolveWebTestStatePaths("soak");
const soakStateEnv = shellEnvironment({
  PREP_WATCHDECK_STATE_DIR: soakPaths.runtimeRoot
});
const cleanupEnv = shellEnvironment({
  WATCHDECK_TEST_RUNTIME_ROOT: soakPaths.runtimeRoot
});

export default defineConfig({
  testDir: "./tests/soak",
  testMatch: "**/*.soak.ts",
  outputDir: soakPaths.playwrightOutputDir,
  workers: 1,
  timeout: soakDurationMs + 300_000,
  expect: {
    timeout: 15_000
  },
  use: {
    baseURL: `http://127.0.0.1:${soakPort}`,
    trace: "retain-on-failure"
  },
  webServer: {
    command: [
      `cd ../web && ${cleanupEnv} bun -e 'import { rmSync } from "node:fs"; rmSync(process.env.WATCHDECK_TEST_RUNTIME_ROOT, { recursive: true, force: true })'`,
      `cd ../scanner-core && ${soakStateEnv} uv run watchdeck scan --source fixture --fixture-set basic --template balanced`,
      "cd ../web && bun run build",
      `${soakStateEnv} bun run preview -- --port ${soakPort}`
    ].join(" && "),
    url: `http://127.0.0.1:${soakPort}/`,
    reuseExistingServer: false,
    timeout: 120_000
  }
});

function positiveInteger(value: string | undefined, fallback: number) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : fallback;
}
