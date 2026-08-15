import { afterEach, describe, expect, test } from "bun:test";
import {
  chmodSync,
  mkdtempSync,
  mkdirSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repoRoot = resolve(import.meta.dirname, "../..");
const portHelper = resolve(repoRoot, "scripts/lib/select-web-port.sh");
const startAll = resolve(repoRoot, "scripts/start-all.sh");
const startLocal = resolve(repoRoot, "scripts/start-local.sh");
const temporaryRoots = [];

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("web port selection", () => {
  test("keeps the requested port when it is available", () => {
    const fixture = createFixture([]);
    const result = selectPort(fixture, "5173");

    expect(result.status).toBe(0);
    expect(result.stdout.trim()).toBe("5173");
    expect(result.stderr).toBe("");
  });

  test("selects the first available port after consecutive conflicts", () => {
    const fixture = createFixture([5173, 5174]);
    const result = selectPort(fixture, "5173");

    expect(result.status).toBe(0);
    expect(result.stdout.trim()).toBe("5175");
    expect(result.stderr).toContain("port 5173 is in use; using 5175");
  });

  test("rejects a port outside the TCP range", () => {
    const fixture = createFixture([]);
    const outOfRange = selectPort(fixture, "70000");
    const oversized = selectPort(fixture, "18446744073709551616");

    expect(outOfRange.status).not.toBe(0);
    expect(outOfRange.stderr).toContain("PORT must be an integer from 1 through 65535");
    expect(oversized.status).not.toBe(0);
    expect(oversized.stderr).toContain("PORT must be an integer from 1 through 65535");
  });

  test("fails when no candidate remains in the TCP range", () => {
    const boundaryFixture = createFixture([65535]);
    const exhaustedFixture = createFixture(
      Array.from({ length: 100 }, (_, index) => 5200 + index)
    );
    const boundary = selectPort(boundaryFixture, "65535");
    const exhausted = selectPort(exhaustedFixture, "5200");

    expect(boundary.status).not.toBe(0);
    expect(boundary.stderr).toContain("no available web port found");
    expect(exhausted.status).not.toBe(0);
    expect(exhausted.stderr).toContain("no available web port found from 5200 through 5299");
  });

  test("start-all starts only the installed user-service boundary", () => {
    const fixture = createFixture([]);
    const result = runScript(startAll, fixture, {
      SYSTEMCTL_BIN: join(fixture.bin, "systemctl")
    });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("url=http://127.0.0.1:5173/");
    expect(result.stdout).toContain(
      "fake-systemctl --user start prep-watchdeck-market-db.service"
    );
    expect(result.stdout).toContain(
      "fake-systemctl --user start prep-watchdeck-market.service"
    );
    expect(result.stdout).toContain(
      "fake-systemctl --user start prep-watchdeck-web.service"
    );
  });

  test("start-local reports and passes the selected fallback port", () => {
    const fixture = createFixture([5173]);
    const result = runScript(startLocal, fixture, { PORT: "5173" });

    expect(result.status).toBe(0);
    expect(result.stderr).toContain("port 5173 is in use; using 5174");
    expect(result.stdout).toContain("url=http://127.0.0.1:5174/");
    expect(result.stdout).toContain("fake-bun run dev -- --port 5174 --strictPort");
  });
});

function createFixture(busyPorts) {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-web-port-"));
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
    {
      encoding: "utf-8",
      env: testEnvironment(fixture)
    }
  );
}

function runScript(script, fixture, env) {
  return spawnSync("bash", [script], {
    encoding: "utf-8",
    env: {
      ...testEnvironment(fixture),
      ...env
    }
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
