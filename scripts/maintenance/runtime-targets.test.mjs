import { afterEach, describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { isIsolatedTestDatabaseUrl } from "../lib/validate-test-database-url.mjs";

const repoRoot = resolve(import.meta.dirname, "../..");
const portHelper = resolve(repoRoot, "scripts/lib/select-web-port.sh");
const startAll = resolve(repoRoot, "scripts/start-all.sh");
const startLocal = resolve(repoRoot, "scripts/start-local.sh");
const temporaryRoots = [];


afterEach(() => {
  for (const root of temporaryRoots.splice(0)) rmSync(root, { recursive: true, force: true });
});


describe("runtime target safety", () => {
  test("selects an available web port and fails closed at invalid or exhausted ranges", () => {
    expect(selectPort(createFixture([]), "5173").stdout.trim()).toBe("5173");

    const fallback = selectPort(createFixture([5173, 5174]), "5173");
    expect(fallback.status).toBe(0);
    expect(fallback.stdout.trim()).toBe("5175");

    const invalid = selectPort(createFixture([]), "70000");
    expect(invalid.status).not.toBe(0);
    expect(invalid.stderr).toContain("PORT must be an integer from 1 through 65535");

    const exhausted = selectPort(createFixture([65535]), "65535");
    expect(exhausted.status).not.toBe(0);
    expect(exhausted.stderr).toContain("no available web port found");
  });

  test("start scripts respect the installed-service boundary and local fallback port", () => {
    const installed = createFixture([]);
    const startInstalled = runScript(startAll, installed, {
      SYSTEMCTL_BIN: join(installed.bin, "systemctl")
    });
    expect(startInstalled.status).toBe(0);
    expect(startInstalled.stdout).toContain("prep-watchdeck-market-db.service");
    expect(startInstalled.stdout).toContain("prep-watchdeck-market.service");
    expect(startInstalled.stdout).toContain("prep-watchdeck-web.service");

    const local = createFixture([5173]);
    const startFallback = runScript(startLocal, local, { PORT: "5173" });
    expect(startFallback.status).toBe(0);
    expect(startFallback.stdout).toContain("url=http://127.0.0.1:5174/");
    expect(startFallback.stdout).toContain("fake-bun run dev -- --port 5174 --strictPort");
  });

  test("accepts only an explicit isolated loopback test database target", () => {
    expect(
      isIsolatedTestDatabaseUrl(
        "postgresql://prep_watchdeck_test:test-only@127.0.0.1:55439/prep_watchdeck_test"
      )
    ).toBe(true);

    for (const target of [
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1:5432/prep_watchdeck_test",
      "postgresql://prep_watchdeck_test:test-only@example.com:55439/prep_watchdeck_test",
      "postgresql://prep_watchdeck_market:test-only@127.0.0.1:55439/prep_watchdeck_test",
      "postgresql://prep_watchdeck_test:test-only@127.0.0.1/prep_watchdeck_test"
    ]) {
      expect(isIsolatedTestDatabaseUrl(target)).toBe(false);
    }
  });
});


function createFixture(busyPorts) {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-runtime-target-"));
  temporaryRoots.push(root);
  const bin = join(root, "bin");
  const state = join(root, "state");
  mkdirSync(bin, { recursive: true });
  mkdirSync(join(state, "snapshots"), { recursive: true });
  writeExecutable(
    join(bin, "lsof"),
    [
      "#!/usr/bin/env bash",
      "case \" $* \" in",
      ...busyPorts.map((port) => `  *\" -iTCP:${port} \"*) exit 0 ;;`),
      "esac",
      "exit 1",
      ""
    ].join("\n")
  );
  writeExecutable(join(bin, "bun"), '#!/usr/bin/env bash\necho "fake-bun $*"\n');
  writeExecutable(join(bin, "uv"), '#!/usr/bin/env bash\necho "fake-uv $*"\n');
  writeExecutable(
    join(bin, "systemctl"),
    '#!/usr/bin/env bash\nif [[ "$2" == "cat" ]]; then exit 0; fi\necho "fake-systemctl $*"\n'
  );
  return { bin, state };
}


function selectPort(fixture, port) {
  return spawnSync(
    "bash",
    ["-c", 'source "$1"; select_watchdeck_web_port "$2"', "bash", portHelper, port],
    { encoding: "utf-8", env: testEnvironment(fixture) }
  );
}


function runScript(script, fixture, env) {
  return spawnSync("bash", [script], {
    encoding: "utf-8",
    env: { ...testEnvironment(fixture), ...env }
  });
}


function testEnvironment(fixture) {
  return {
    HOME: process.env.HOME,
    PATH: `${fixture.bin}:${process.env.PATH}`,
    PREP_WATCHDECK_MARKET_STATE_DIR: fixture.state
  };
}


function writeExecutable(path, content) {
  writeFileSync(path, content);
  chmodSync(path, 0o755);
}
