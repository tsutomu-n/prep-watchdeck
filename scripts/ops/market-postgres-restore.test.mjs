import { afterEach, describe, expect, test } from "bun:test";
import { spawnSync } from "node:child_process";
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
const script = join(repoRoot, "scripts/ops/market-postgres-restore.sh");
const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("market-postgres-restore", () => {
  test("preserves the explicit production restore contract by default", () => {
    const fixture = createFixture({
      project: "prep-watchdeck-market",
      database: "prep_watchdeck_market",
    });
    const result = spawnSync(
      "bash",
      [
        script,
        "--state-root",
        fixture.stateRoot,
        "--env-file",
        fixture.envFile,
        "--backup",
        fixture.backup,
        "--confirm-target",
        fixture.database,
        "--apply",
      ],
      { encoding: "utf8", env: fixture.env },
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(`target=${fixture.database}`);
    expect(readFileSync(fixture.dockerLog, "utf8")).toContain(
      `--project-name ${fixture.project}`,
    );
  });

  test("restores a production archive only to an explicitly confirmed isolated target", () => {
    const fixture = createFixture();
    const result = spawnSync(
      "bash",
      [
        script,
        "--state-root",
        fixture.stateRoot,
        "--env-file",
        fixture.envFile,
        "--backup",
        fixture.backup,
        "--compose-project",
        fixture.project,
        "--target-database",
        fixture.database,
        "--confirm-target",
        fixture.database,
        "--apply",
      ],
      { encoding: "utf8", env: fixture.env },
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain(`target=${fixture.database}`);
    const dockerLog = readFileSync(fixture.dockerLog, "utf8");
    expect(dockerLog).toContain(`--project-name ${fixture.project}`);
    expect(dockerLog).toContain("pg_restore --list");
    expect(readdirSync(fixture.stateRoot)).not.toContain(
      expect.stringContaining(".market-restore."),
    );
  });

  test("refuses a non-production project without a non-production database", () => {
    const fixture = createFixture();
    const result = spawnSync(
      "bash",
      [
        script,
        "--state-root",
        fixture.stateRoot,
        "--env-file",
        fixture.envFile,
        "--backup",
        fixture.backup,
        "--compose-project",
        fixture.project,
        "--confirm-target",
        "prep_watchdeck_market",
        "--apply",
      ],
      { encoding: "utf8", env: fixture.env },
    );

    expect(result.status).toBe(2);
    expect(result.stderr).toContain("isolated restore must override both project and database");
  });
});

function createFixture({
  project = "prep-watchdeck-market-restore-test",
  database = "prep_watchdeck_market_restore_test",
} = {}) {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-restore-"));
  roots.push(root);
  const bin = join(root, "bin");
  const stateRoot = join(root, "state");
  const envFile = join(root, "postgres.env");
  const backup = join(root, "production.dump");
  const dockerLog = join(root, "docker.log");
  mkdirSync(bin, { recursive: true });
  mkdirSync(join(stateRoot, "postgres"), { recursive: true });
  writeFileSync(
    envFile,
    `POSTGRES_DB=${database}\nPOSTGRES_USER=${database}\nPOSTGRES_PASSWORD=test-only\n`,
  );
  chmodSync(envFile, 0o600);
  writeFileSync(backup, "fake custom archive\n");
  chmodSync(backup, 0o600);
  const docker = join(bin, "docker");
  writeFileSync(
    docker,
    `#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${dockerLog}"
if [[ "$1" == "inspect" ]]; then
  case "$3" in
    *compose.project*) printf '%s\\n' "${project}" ;;
    *compose.service*) printf '%s\\n' postgres ;;
    *Destination*) printf '%s\\n' "${stateRoot}/postgres" ;;
  esac
  exit 0
fi
arguments=" $* "
if [[ "$arguments" == *" ps --status running --quiet postgres "* ]]; then
  printf '%s\\n' container-id
elif [[ "$arguments" == *" exec -T postgres pg_restore --list "* ]]; then
  cat >/dev/null
  printf '%s\\n' '; dbname: prep_watchdeck_market'
elif [[ "$arguments" == *" exec -T postgres pg_restore --file=- "* ]]; then
  cat >/dev/null
  printf '%s\\n' 'CREATE TABLE restored_probe (id integer);'
elif [[ "$arguments" == *'printf "%s\\n" "$POSTGRES_DB"'* ]]; then
  printf '%s\\n' "${database}"
elif [[ "$arguments" == *"pg_stat_activity"* ]]; then
  printf '%s\\n' 0
else
  cat >/dev/null || true
fi
`,
  );
  chmodSync(docker, 0o755);
  return {
    stateRoot,
    envFile,
    backup,
    dockerLog,
    project,
    database,
    env: { ...process.env, PATH: `${bin}:${process.env.PATH ?? ""}` },
  };
}
