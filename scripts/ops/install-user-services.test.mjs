import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const script = join(repoRoot, "scripts/ops/install-user-services.sh");
const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("install-user-services", () => {
  test("renders the new DB, collector, maintenance, and Web boundaries", () => {
    const fixture = createFixture();
    const commonArgs = args(fixture);

    const dryRun = spawnSync("bash", commonArgs, { encoding: "utf8" });
    expect(dryRun.status).toBe(0);
    expect(dryRun.stdout).toContain("mode=dry-run");
    expect(readdirSync(fixture.root)).not.toContain("units");

    execFileSync("bash", [...commonArgs, "--apply"]);

    const db = read(fixture, "prep-watchdeck-market-db.service");
    const market = read(fixture, "prep-watchdeck-market.service");
    const maintenance = read(fixture, "prep-watchdeck-market-maintenance.service");
    const timer = read(fixture, "prep-watchdeck-market-maintenance.timer");
    const web = read(fixture, "prep-watchdeck-web.service");

    expect(db).toContain("--project-name prep-watchdeck-market");
    expect(db).toContain(`Environment=PREP_WATCHDECK_MARKET_STATE_DIR=${fixture.stateRoot}`);
    expect(db).toContain("Environment=DOCKER_HOST=unix:///var/run/docker.sock");
    expect(db).toContain("UnsetEnvironment=DOCKER_CONTEXT");
    expect(market).toContain(`WorkingDirectory=${repoRoot}/apps/market-core`);
    expect(market).toContain(`EnvironmentFile=${fixture.envFile}`);
    expect(market).toContain("run watchdeck-market migrate");
    expect(db).toContain("Environment=PREP_WATCHDECK_MARKET_DB_PORT=55432");
    expect(market).toContain(
      "UnsetEnvironment=PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET",
    );
    expect(market).not.toContain("/usr/bin/flock");
    expect(market).toContain("run watchdeck-market service");
    expect(maintenance).toContain("scripts/ops/run-market-maintenance.sh");
    expect(maintenance).toContain(`Environment=PREP_WATCHDECK_MARKET_UV_BIN=${fixture.uv}`);
    expect(timer).toContain("OnCalendar=hourly");
    expect(timer).toContain("Persistent=true");
    expect(web).toContain(`Environment=PREP_WATCHDECK_MARKET_STATE_DIR=${fixture.stateRoot}`);
    expect(web).toContain(`WorkingDirectory=${repoRoot}/apps/web`);
    expect(web).toContain(`ExecStart=${fixture.bun} run dev -- --port 5173 --strictPort`);
    expect(readFileSync(fixture.systemctlLog, "utf8")).toBe(
      "--user daemon-reload\n" +
        "--user enable prep-watchdeck-market-db.service prep-watchdeck-market.service " +
        "prep-watchdeck-web.service prep-watchdeck-market-maintenance.timer\n",
    );

    const check = spawnSync("bash", [...commonArgs, "--check"], { encoding: "utf8" });
    expect(check.status).toBe(0);
    expect(check.stdout).toContain("units match rendered configuration");

    const marketPath = join(fixture.unitDir, "prep-watchdeck-market.service");
    writeFileSync(marketPath, "old-unit\n");
    execFileSync("bash", [...commonArgs, "--apply"]);
    const backups = readdirSync(fixture.unitDir).filter((name) =>
      name.startsWith("prep-watchdeck-market.service.bak."),
    );
    expect(backups).toHaveLength(1);
    expect(readFileSync(join(fixture.unitDir, backups[0]), "utf8")).toBe("old-unit\n");
  });

  test("refuses apply when the external credential file is not mode 600", () => {
    const fixture = createFixture();
    chmodSync(fixture.envFile, 0o644);

    const result = spawnSync("bash", [...args(fixture), "--apply"], { encoding: "utf8" });

    expect(result.status).toBe(2);
    expect(result.stderr).toContain("market env file mode must be 600");
    expect(readdirSync(fixture.root)).not.toContain("units");
  });

  test("refuses apply when the database URL is not the dedicated local target", () => {
    const fixture = createFixture();
    writeFileSync(
      fixture.envFile,
      "PREP_WATCHDECK_MARKET_DATABASE_URL=" +
        "postgresql://prep_watchdeck_market:secret@127.0.0.1:5432/prep_watchdeck_market\n",
    );
    chmodSync(fixture.envFile, 0o600);

    const result = spawnSync("bash", [...args(fixture), "--apply"], { encoding: "utf8" });

    expect(result.status).toBe(2);
    expect(result.stderr).toContain("must target the dedicated local database");
    expect(readdirSync(fixture.root)).not.toContain("units");
  });
});

function createFixture() {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-systemd-"));
  roots.push(root);
  const bin = join(root, "bin");
  const unitDir = join(root, "units");
  const stateRoot = join(root, "state");
  const configDir = join(root, "config");
  const envFile = join(configDir, "postgres.env");
  const systemctlLog = join(root, "systemctl.log");
  mkdirSync(bin, { recursive: true });
  mkdirSync(configDir, { recursive: true });
  writeFileSync(
    envFile,
    "PREP_WATCHDECK_MARKET_DATABASE_URL=" +
      "postgresql://prep_watchdeck_market:secret@127.0.0.1:55432/prep_watchdeck_market\n",
  );
  chmodSync(envFile, 0o600);
  for (const name of ["systemctl", "uv", "bun", "docker"]) {
    const path = join(bin, name);
    writeFileSync(
      path,
      name === "systemctl"
        ? `#!/usr/bin/env bash\nprintf '%s\\n' "$*" >> "${systemctlLog}"\n`
        : "#!/usr/bin/env bash\nexit 0\n",
    );
    chmodSync(path, 0o755);
  }
  return {
    root,
    unitDir,
    stateRoot,
    envFile,
    systemctlLog,
    systemctl: join(bin, "systemctl"),
    uv: join(bin, "uv"),
    bun: join(bin, "bun"),
    docker: join(bin, "docker"),
  };
}

function args(fixture) {
  return [
    script,
    "--repo-root",
    repoRoot,
    "--state-root",
    fixture.stateRoot,
    "--market-env-file",
    fixture.envFile,
    "--unit-dir",
    fixture.unitDir,
    "--systemctl-bin",
    fixture.systemctl,
    "--uv-bin",
    fixture.uv,
    "--bun-bin",
    fixture.bun,
    "--docker-bin",
    fixture.docker,
  ];
}

function read(fixture, name) {
  return readFileSync(join(fixture.unitDir, name), "utf8");
}
