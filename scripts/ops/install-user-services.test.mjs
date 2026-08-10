import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
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
  test("dry-runs, applies with backup, and detects unit drift", () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-systemd-"));
    roots.push(root);
    const unitDir = join(root, "units");
    const stateRoot = join(root, "state");
    const systemctlLog = join(root, "systemctl.log");
    const fakeSystemctl = join(root, "systemctl");
    writeFileSync(
      fakeSystemctl,
      `#!/usr/bin/env bash\nprintf '%s\\n' "$*" >> "${systemctlLog}"\n`,
    );
    chmodSync(fakeSystemctl, 0o755);

    const commonArgs = [
      script,
      "--repo-root",
      repoRoot,
      "--state-root",
      stateRoot,
      "--unit-dir",
      unitDir,
      "--systemctl-bin",
      fakeSystemctl,
    ];

    const dryRun = spawnSync("bash", commonArgs, { encoding: "utf8" });
    expect(dryRun.status).toBe(0);
    expect(dryRun.stdout).toContain("mode=dry-run");
    expect(readdirSync(root)).not.toContain("units");

    execFileSync("bash", [...commonArgs, "--apply"]);
    const servicePath = join(unitDir, "prep-watchdeck-service.service");
    const webPath = join(unitDir, "prep-watchdeck-web.service");
    const service = readFileSync(servicePath, "utf8");
    const web = readFileSync(webPath, "utf8");

    expect(service).toContain(`WorkingDirectory=${repoRoot}/apps/scanner-core`);
    expect(service).toContain(`Environment=PREP_WATCHDECK_STATE_DIR=${stateRoot}`);
    expect(service).toContain("--backfill-limit 0 --reconcile-concurrency 1");
    expect(service).toContain("--ticker-refresh-interval-sec 60");
    expect(service).toContain("--deep-backfill-limit 5885");
    expect(service).toContain("--deep-backfill-rate-limit-per-second 1");
    expect(service).toContain("TimeoutStopSec=90s");
    expect(web).toContain(`ExecStart=/usr/bin/bash ${repoRoot}/scripts/start-all.sh`);
    expect(web).toContain("Environment=SNAPSHOT_SOURCE=skip");
    expect(readFileSync(systemctlLog, "utf8")).toBe(
      "--user daemon-reload\n" +
        "--user enable prep-watchdeck-service.service prep-watchdeck-web.service\n",
    );

    const check = spawnSync("bash", [...commonArgs, "--check"], { encoding: "utf8" });
    expect(check.status).toBe(0);
    expect(check.stdout).toContain("units match rendered configuration");

    writeFileSync(servicePath, "old-unit\n");
    execFileSync("bash", [...commonArgs, "--apply"]);
    const backups = readdirSync(unitDir).filter((name) =>
      name.startsWith("prep-watchdeck-service.service.bak."),
    );
    expect(backups).toHaveLength(1);
    expect(readFileSync(join(unitDir, backups[0]), "utf8")).toBe("old-unit\n");

    writeFileSync(webPath, `${web}# drift\n`);
    const drift = spawnSync("bash", [...commonArgs, "--check"], { encoding: "utf8" });
    expect(drift.status).toBe(1);
    expect(drift.stderr).toContain("unit drift detected");
  });
});
