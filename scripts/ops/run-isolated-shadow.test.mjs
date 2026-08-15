import { afterEach, describe, expect, test } from "bun:test";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repoRoot = resolve(import.meta.dirname, "../..");
const script = join(repoRoot, "scripts/ops/run-isolated-shadow.sh");
const temporaryRoots = [];

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("run-isolated-shadow", () => {
  test("dry-run requires explicit isolated targets and performs no writes", () => {
    const fixture = createFixture();
    const result = spawnSync("bash", args(fixture), { encoding: "utf8" });

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("mode=dry-run");
    expect(result.stdout).toContain(
      "baselineSeconds=2 shadowSeconds=3 sampleSeconds=1",
    );
    expect(result.stdout).toContain(
      "databaseOverride=PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=true",
    );
    expect(result.stdout).toContain(
      "webMode=build-once-before-baseline-then-preview",
    );
    expect(result.stdout).toContain(
      "dockerHost=unix:///var/run/docker.sock dockerContext=unset",
    );
    expect(result.stdout).toContain(
      "no directory, container, process, API, database, service",
    );
    expect(existsSync(fixture.stateRoot)).toBe(false);
    expect(existsSync(fixture.evidenceRoot)).toBe(false);
  });

  test("rejects JustPass and production-default ports before execution", () => {
    const fixture = createFixture();
    const justPass = spawnSync(
      "bash",
      [...args(fixture), "--db-port", "5432"],
      {
        encoding: "utf8",
      },
    );
    const productionWeb = spawnSync(
      "bash",
      [...args(fixture), "--web-port", "5173"],
      { encoding: "utf8" },
    );

    expect(justPass.status).toBe(2);
    expect(justPass.stderr).toContain(
      "JustPass 5432 or production default 55432",
    );
    expect(productionWeb.status).toBe(2);
    expect(productionWeb.stderr).toContain("production default 5173");
  });

  test("counts only structured 429 source error codes", () => {
    const fixture = createFixture();
    const source = readFileSync(script, "utf8");
    const program = source.match(
      /awk '\n([\s\S]*?)\n' "\$evidence_dir\/market-service\.log"/,
    );
    const log = join(fixture.root, "market.log");
    writeFileSync(
      log,
      [
        "stored=429 error_codes=none",
        "l1_cycle error_codes=bitget:http_429,aster:invalid_payload grid_skips=0",
        "l1_cycle error_codes=bitget:bitget_business_429 grid_skips=0",
        "unstructured response 429",
        "",
      ].join("\n"),
    );

    expect(program).not.toBeNull();
    expect(source).toContain("error_codes=[^[:space:]]+");
    expect(source).toContain("http_429|bitget_business_429");
    expect(source).not.toContain("grep -Eic '(^|[^0-9])429");
    const result = spawnSync("awk", [program[1], log], { encoding: "utf8" });
    expect(result.status).toBe(0);
    expect(result.stdout.trim()).toBe("2");
  });

  test("binds evidence to tracked and untracked source contents", () => {
    const source = readFileSync(script, "utf8");

    expect(source).toContain(
      'git -C "$repo_root" diff --binary --no-ext-diff --full-index HEAD',
    );
    expect(source).toContain(
      'git -C "$repo_root" ls-files --others --exclude-standard -z',
    );
    expect(source).toContain("source-digest-before.txt");
    expect(source).toContain("source-digest-after.txt");
    expect(source).toContain("source changed during isolated shadow");
  });

  test("cleanup continues when an owned process group already exited", () => {
    const source = readFileSync(script, "utf8");
    const helper = source.match(/kill_owned_group\(\) \{([\s\S]*?)\n\}/);

    expect(helper).not.toBeNull();
    expect(helper[1].trimEnd().endsWith("return 0")).toBe(true);
  });

  test("allows a transient zero DuckDB opener but rejects multiple openers", () => {
    const source = readFileSync(script, "utf8");

    expect(source).toContain(
      'all(int(row["duckdbOpeners"]) <= 1 for row in all_rows)',
    );
    expect(source).toContain(
      'any(int(row["duckdbOpeners"]) == 1 for row in all_rows)',
    );
    expect(source).not.toContain(
      'all(int(row["duckdbOpeners"]) == 1 for row in all_rows)',
    );
  });

  test("includes both raw partition trees in the capacity projection", () => {
    const source = readFileSync(script, "utf8");
    const helper = source.match(/raw_relation_bytes\(\) \{([\s\S]*?)\n\}/);

    expect(helper).not.toBeNull();
    expect(helper[1]).toContain(
      "pg_partition_tree('raw_market_observations'::regclass)",
    );
    expect(helper[1]).toContain(
      "pg_partition_tree('selected_raw_observations'::regclass)",
    );
    expect(helper[1]).toContain("UNION ALL");
    expect(helper[1].match(/WHERE isleaf/g)).toHaveLength(2);
  });

  test("holds when the final snapshot is stale despite a normal interval ratio", () => {
    const fixture = createFixture();
    const source = readFileSync(script, "utf8");
    const program = source.match(/<<'PY'\n([\s\S]*?)\nPY/);
    const header = [
      "sampledAt",
      "snapshotMtime",
      "nRestarts",
      "duckdbOpeners",
      "hostRxBytes",
      "hostTxBytes",
      "marketCpuPct",
      "marketRssKb",
      "webCpuPct",
      "webRssKb",
    ].join("\t");
    const row = (sampledAt, snapshotMtime) =>
      [sampledAt, snapshotMtime, 0, 1, sampledAt, sampledAt, 0, 1, 0, 1].join(
        "\t",
      );
    const baseline = join(fixture.root, "baseline.tsv");
    const shadow = join(fixture.root, "shadow.tsv");
    const capacity = join(fixture.root, "capacity.json");
    const output = join(fixture.root, "summary.json");
    writeFileSync(
      baseline,
      [header, row(1000, 1000), row(1060, 1060), row(1120, 1120), ""].join(
        "\n",
      ),
    );
    writeFileSync(
      shadow,
      [header, row(2000, 2000), row(2060, 2060), row(2300, 2060), ""].join(
        "\n",
      ),
    );
    writeFileSync(
      capacity,
      JSON.stringify({
        projectionComplete: true,
        projectedParquetGbPerDay: 0,
        requiredMissingPartitions: [],
        optionalEmptyPartitions: [],
      }),
    );

    expect(program).not.toBeNull();
    const result = spawnSync(
      "/usr/bin/python3",
      [
        "-",
        baseline,
        shadow,
        capacity,
        output,
        "120",
        "300",
        "0",
        "0",
        "0",
        "0",
        "1000000000000",
        "0",
      ],
      { input: program[1], encoding: "utf8" },
    );
    const summary = JSON.parse(readFileSync(output, "utf8"));

    expect(result.status).toBe(0);
    expect(summary.measurement.snapshotP95Ratio).toBe(1);
    expect(summary.measurement.shadowTerminalSnapshotAgeSeconds).toBe(240);
    expect(summary.measurement.terminalSnapshotFresh).toBe(false);
    expect(summary.existingRuntimeImpactPass).toBe(false);
    expect(summary.status).toBe("hold");
  });
});

function createFixture() {
  const root = mkdtempSync(join(tmpdir(), "watchdeck-shadow-test-"));
  temporaryRoots.push(root);
  return {
    root,
    stateRoot: join(root, "shadow-state"),
    evidenceRoot: join(root, "evidence"),
    liveStateRoot: join(root, "live-state"),
  };
}

function args(fixture) {
  return [
    script,
    "--dry-run",
    "--repo-root",
    repoRoot,
    "--state-root",
    fixture.stateRoot,
    "--evidence-root",
    fixture.evidenceRoot,
    "--live-state-root",
    fixture.liveStateRoot,
    "--live-snapshot",
    join(fixture.liveStateRoot, "snapshots", "latest.json"),
    "--live-duckdb",
    join(fixture.liveStateRoot, "watchdeck.duckdb"),
    "--live-scanner-unit",
    "prep-watchdeck-service.service",
    "--compose-project",
    "prep-watchdeck-market-shadow-test",
    "--db-port",
    "55442",
    "--web-port",
    "5183",
    "--baseline-seconds",
    "2",
    "--shadow-seconds",
    "3",
    "--sample-seconds",
    "1",
  ];
}
