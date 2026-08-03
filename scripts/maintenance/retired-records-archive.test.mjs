import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync, spawnSync } from "node:child_process";
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";

const archiveScript = resolve(import.meta.dirname, "archive-retired-records.sh");
const verifyScript = resolve(import.meta.dirname, "verify-retired-records-archive.sh");
const createdRoots = [];

afterEach(() => {
  for (const root of createdRoots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("retired record archive", () => {
  test("copies every data file, records hashes and raw counts, restores a smoke copy, and keeps source", () => {
    const fixture = createFixture();
    write(
      fixture.repo,
      "var/trade-memos/current.json",
      JSON.stringify({ memos: [{ id: "memo-1" }, { id: "memo-2" }] }) + "\n"
    );
    write(fixture.repo, "var/trade-memos/nested/evidence.txt", "opaque bytes\n");
    write(fixture.repo, "var/trade-memos/.gitkeep", "");
    write(
      fixture.repo,
      "var/attack-tickets/current.json",
      JSON.stringify({ tickets: [{ id: "ticket-1" }] }) + "\n"
    );
    const sourceMemo = readFileSync(join(fixture.repo, "var/trade-memos/current.json"));

    const result = runArchive(fixture);

    expect(result.status).toBe(0);
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(true);
    expect(existsSync(join(fixture.archive, "retired-state/trade-memos/current.json"))).toBe(true);
    expect(existsSync(join(fixture.archive, "retired-state/trade-memos/nested/evidence.txt"))).toBe(
      true
    );
    expect(existsSync(join(fixture.archive, "retired-state/trade-memos/.gitkeep"))).toBe(false);
    expect(readFileSync(join(fixture.repo, "var/trade-memos/current.json"))).toEqual(sourceMemo);

    const manifest = JSON.parse(readFileSync(join(fixture.archive, "manifest.json"), "utf-8"));
    expect(manifest.schemaVersion).toBe(1);
    expect(manifest.kind).toBe("prep-watchdeck-retired-records-archive");
    expect(manifest.sources.tradeMemos.currentJson).toEqual({
      status: "valid",
      rawRecordCount: 2
    });
    expect(manifest.sources.attackTickets.currentJson).toEqual({
      status: "valid",
      rawRecordCount: 1
    });
    expect(manifest.files.map((entry) => entry.path)).toEqual([
      "attack-tickets/current.json",
      "trade-memos/current.json",
      "trade-memos/nested/evidence.txt"
    ]);
    expect(manifest.files.every((entry) => entry.bytes >= 0 && /^[0-9a-f]{64}$/.test(entry.sha256))).toBe(
      true
    );
    expect(manifest.ignored).toEqual([
      { path: "trade-memos/.gitkeep", reason: "tracked-placeholder" }
    ]);
    expect(manifest.restoreSmoke).toEqual({ verified: true, fileCount: 3 });
    expect(readFileSync(join(fixture.archive, "FILES_SHA256"), "utf-8")).toContain(
      "trade-memos/current.json"
    );

    const verify = runVerify(fixture.archive);
    expect(verify.status).toBe(0);
    expect(verify.stdout).toContain("verification=passed");
  });

  test("archives missing record directories as an explicit zero-record state", () => {
    const fixture = createFixture();

    const result = runArchive(fixture);

    expect(result.status).toBe(0);
    const manifest = JSON.parse(readFileSync(join(fixture.archive, "manifest.json"), "utf-8"));
    expect(manifest.sources.tradeMemos.exists).toBe(false);
    expect(manifest.sources.tradeMemos.currentJson).toEqual({
      status: "missing",
      rawRecordCount: 0
    });
    expect(manifest.sources.attackTickets.exists).toBe(false);
    expect(manifest.files).toEqual([]);
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(true);
  });

  test("accepts valid empty envelopes", () => {
    const fixture = createFixture();
    write(fixture.repo, "var/trade-memos/current.json", '{"memos":[]}\n');
    write(fixture.repo, "var/attack-tickets/current.json", '{"tickets":[]}\n');

    const result = runArchive(fixture);

    expect(result.status).toBe(0);
    const manifest = JSON.parse(readFileSync(join(fixture.archive, "manifest.json"), "utf-8"));
    expect(manifest.sources.tradeMemos.currentJson.rawRecordCount).toBe(0);
    expect(manifest.sources.attackTickets.currentJson.rawRecordCount).toBe(0);
  });

  test("fails before verification on invalid JSON without printing record contents", () => {
    const fixture = createFixture();
    write(fixture.repo, "var/trade-memos/current.json", "SECRET_RECORD_CONTENT {\n");

    const result = runArchive(fixture);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("trade memos current.json is not valid JSON");
    expect(result.stderr).not.toContain("SECRET_RECORD_CONTENT");
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(false);
  });

  test("fails closed on a wrong current.json envelope", () => {
    const fixture = createFixture();
    write(fixture.repo, "var/attack-tickets/current.json", '{"tickets":"not-an-array"}\n');

    const result = runArchive(fixture);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("attack tickets current.json must contain a tickets array");
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(false);
  });

  test("refuses lock and atomic temporary files instead of copying a moving store", () => {
    const fixture = createFixture();
    write(fixture.repo, "var/trade-memos/current.json", '{"memos":[]}\n');
    write(fixture.repo, "var/trade-memos/current.json.lock", '{"pid":123}\n');
    write(fixture.repo, "var/attack-tickets/.current.json.123.456.uuid.tmp", "partial\n");

    const result = runArchive(fixture);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("lock or temporary files exist in retired record state");
    expect(result.stderr).not.toContain('{"pid":123}');
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(false);
  });

  test("uses prefixed and legacy directory overrides with their current working-directory semantics", () => {
    const fixture = createFixture();
    write(fixture.repo, "apps/scanner-core/custom-memos/current.json", '{"memos":[{"id":"m"}]}\n');
    write(fixture.repo, "apps/web/legacy-tickets/current.json", '{"tickets":[{"id":"t"}]}\n');

    const result = runArchive(fixture, {
      PREP_WATCHDECK_TRADE_MEMOS_DIR: "custom-memos",
      ATTACK_TICKETS_DIR: "legacy-tickets"
    });

    expect(result.status).toBe(0);
    const manifest = JSON.parse(readFileSync(join(fixture.archive, "manifest.json"), "utf-8"));
    expect(manifest.sources.tradeMemos.path).toBe(
      join(fixture.repo, "apps/scanner-core/custom-memos")
    );
    expect(manifest.sources.attackTickets.path).toBe(
      join(fixture.repo, "apps/web/legacy-tickets")
    );
    expect(manifest.sources.tradeMemos.currentJson.rawRecordCount).toBe(1);
    expect(manifest.sources.attackTickets.currentJson.rawRecordCount).toBe(1);
  });

  test("test harness does not inherit an unrelated parent state root", () => {
    const fixture = createFixture();
    const unrelatedState = newTempDir("prep-watchdeck-unrelated-state-");
    write(fixture.repo, "var/trade-memos/current.json", '{"memos":[{"id":"fixture"}]}\n');
    writeFile(
      join(unrelatedState, "trade-memos/current.json"),
      '{"memos":[{"id":"unrelated"},{"id":"unrelated-2"}]}\n'
    );

    const result = runArchive(
      fixture,
      {},
      { ...process.env, PREP_WATCHDECK_STATE_DIR: unrelatedState }
    );

    expect(result.status).toBe(0);
    const manifest = JSON.parse(readFileSync(join(fixture.archive, "manifest.json"), "utf-8"));
    expect(manifest.sources.tradeMemos.path).toBe(join(fixture.repo, "var/trade-memos"));
    expect(manifest.sources.tradeMemos.currentJson.rawRecordCount).toBe(1);
  });

  test("refuses an archive inside the repository or a non-empty archive", () => {
    const fixture = createFixture();
    const inside = join(fixture.repo, "archive");
    mkdirSync(inside, { recursive: true });

    const insideResult = runArchive({ ...fixture, archive: inside });
    expect(insideResult.status).not.toBe(0);
    expect(insideResult.stderr).toContain("archive directory must be outside the repository");

    writeFileSync(join(fixture.archive, "keep.txt"), "do not overwrite\n");
    const nonEmptyResult = runArchive(fixture);
    expect(nonEmptyResult.status).not.toBe(0);
    expect(nonEmptyResult.stderr).toContain("archive directory must not already contain files");
    expect(readFileSync(join(fixture.archive, "keep.txt"), "utf-8")).toBe("do not overwrite\n");
  });

  test("detects a source change made after copying", () => {
    const fixture = createFixture();
    const sourcePath = join(fixture.repo, "var/trade-memos/current.json");
    writeFile(sourcePath, '{"memos":[{"id":"before"}]}\n');
    const fakeBin = newTempDir("prep-watchdeck-retired-fake-bin-");
    const marker = join(fakeBin, "mutated");
    writeFile(
      join(fakeBin, "rsync"),
      [
        "#!/usr/bin/env bash",
        'set -euo pipefail',
        '/usr/bin/rsync "$@"',
        'if [[ ! -e "$WATCHDECK_TEST_MUTATION_MARKER" ]]; then',
        '  printf \'%s\\n\' \'{"memos":[{"id":"after"}]}\' >"$WATCHDECK_TEST_MUTATE_SOURCE"',
        '  touch "$WATCHDECK_TEST_MUTATION_MARKER"',
        "fi",
        ""
      ].join("\n")
    );
    chmodSync(join(fakeBin, "rsync"), 0o755);

    const result = runArchive(fixture, {
      PATH: `${fakeBin}:${process.env.PATH}`,
      WATCHDECK_TEST_MUTATE_SOURCE: sourcePath,
      WATCHDECK_TEST_MUTATION_MARKER: marker
    });

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("retired record source changed during archive copy");
    expect(existsSync(join(fixture.archive, "ARCHIVE_VERIFIED"))).toBe(false);
  });

  test("verification rejects an archived byte change", () => {
    const fixture = createFixture();
    write(fixture.repo, "var/trade-memos/current.json", '{"memos":[{"id":"memo"}]}\n');
    expect(runArchive(fixture).status).toBe(0);
    writeFileSync(
      join(fixture.archive, "retired-state/trade-memos/current.json"),
      '{"memos":[]}\n'
    );

    const result = runVerify(fixture.archive);

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("archive files do not match manifest");
  });
});

function createFixture() {
  const repo = newTempDir("prep-watchdeck-retired-repo-");
  const archive = newTempDir("prep-watchdeck-retired-archive-");
  mkdirSync(join(repo, "apps/scanner-core"), { recursive: true });
  mkdirSync(join(repo, "apps/web"), { recursive: true });
  execFileSync("git", ["init", "-q"], { cwd: repo });
  execFileSync("git", ["config", "user.email", "fixture@example.invalid"], { cwd: repo });
  execFileSync("git", ["config", "user.name", "Fixture"], { cwd: repo });
  write(repo, "README.md", "fixture\n");
  execFileSync("git", ["add", "README.md"], { cwd: repo });
  execFileSync("git", ["commit", "-qm", "fixture"], { cwd: repo });
  return { repo, archive };
}

function runArchive(fixture, env = {}, parentEnv = process.env) {
  const cleanEnv = { ...parentEnv };
  for (const name of [
    "PREP_WATCHDECK_STATE_DIR",
    "PREP_WATCHDECK_TRADE_MEMOS_DIR",
    "TRADE_MEMOS_DIR",
    "PREP_WATCHDECK_ATTACK_TICKETS_DIR",
    "ATTACK_TICKETS_DIR"
  ]) {
    delete cleanEnv[name];
  }
  return spawnSync(
    "bash",
    [archiveScript, "--repo-root", fixture.repo, "--archive-dir", fixture.archive],
    {
      encoding: "utf-8",
      env: { ...cleanEnv, ...env }
    }
  );
}

function runVerify(archive) {
  return spawnSync("bash", [verifyScript, "--archive-dir", archive], {
    encoding: "utf-8"
  });
}

function write(root, relativePath, content) {
  writeFile(join(root, relativePath), content);
}

function writeFile(path, content) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function newTempDir(prefix) {
  const root = mkdtempSync(join(tmpdir(), prefix));
  createdRoots.push(root);
  return root;
}
