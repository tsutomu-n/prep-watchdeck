import { afterEach, describe, expect, test } from "bun:test";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  mkdirSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  isDocumentTarget,
  validateHtmlDocument,
  validateMarkdownDocument
} from "./check-document-metadata.mjs";
import { workingTreePaths } from "./document-paths.mjs";
import {
  formatJstTimestamp,
  updateMarkdownMetadata
} from "./update-document-timestamp.mjs";

const createdAt = "2026-06-18T04:43:28+09:00";
const updatedAt = "2026-07-16T22:55:00+09:00";
const verifiedAt = "2026-07-16T22:56:00+09:00";
const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("document metadata targets", () => {
  test("includes Git-managed human docs and excludes archives and generated paths", () => {
    expect(isDocumentTarget("README.md")).toBe(true);
    expect(isDocumentTarget("DESIGN.md")).toBe(true);
    expect(isDocumentTarget("AGENTS.md")).toBe(true);
    expect(isDocumentTarget("docs/current/overview.md")).toBe(true);
    expect(isDocumentTarget("docs/current/reference.html")).toBe(true);
    expect(isDocumentTarget("config/scanner-filters/README.md")).toBe(true);
    expect(isDocumentTarget("apps/web/README.md")).toBe(true);

    expect(isDocumentTarget("docs/archive/old.md")).toBe(false);
    expect(isDocumentTarget("docs/local-archive/old.md")).toBe(false);
    expect(isDocumentTarget("mockups/example/README.md")).toBe(false);
    expect(isDocumentTarget("apps/web/src/lib/generated/types.md")).toBe(false);
    expect(isDocumentTarget("fixtures/README.md")).toBe(false);
    expect(isDocumentTarget("src/example.ts")).toBe(false);
  });

  test("includes untracked non-ignored files and skips deleted tracked files", () => {
    const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-document-paths-"));
    roots.push(root);
    execFileSync("git", ["init", "--quiet"], { cwd: root });
    write(root, ".gitignore", "ignored/\n");
    write(root, "README.md", "# Root\n");
    write(root, "docs/deleted.md", "# Deleted\n");
    execFileSync("git", ["add", ".gitignore", "README.md", "docs/deleted.md"], {
      cwd: root
    });
    rmSync(join(root, "docs/deleted.md"));
    write(root, "docs/current/overview.md", "# Current\n");
    write(root, "ignored/reference.md", "# Ignored\n");

    expect(workingTreePaths(root)).toEqual([
      ".gitignore",
      "README.md",
      "docs/current/overview.md"
    ]);
  });
});

describe("Markdown metadata validation", () => {
  test("accepts a current document with ISO 8601 JST metadata", () => {
    const errors = validateMarkdownDocument(
      "docs/current/overview.md",
      markdown({
        created: createdAt,
        updated: updatedAt,
        verified: verifiedAt,
        status: "現行"
      })
    );

    expect(errors).toEqual([]);
  });

  test("requires H1, created, updated, an allowed status, and current verification", () => {
    const errors = validateMarkdownDocument(
      "docs/current/overview.md",
      [
        "overview",
        "",
        `- 作成: \`${createdAt}\``,
        "- 更新: `2026-07-16_22:55`",
        "- 状態: `履歴`"
      ].join("\n")
    );

    expect(errors).toContain("H1見出しがありません");
    expect(errors).toContain("更新は YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください");
    expect(errors).toContain("状態は 現行 / 設計判断 / 実装計画 / 検証記録 / 参考 のいずれかです");
    expect(errors).toContain("docs/current/ では検証が必須です");
  });

  test("rejects timestamps after line 15 and update times before creation", () => {
    const lateMetadata = [
      "# Late metadata",
      ...Array.from({ length: 15 }, (_, index) => `line ${index + 1}`),
      `- 作成: \`${createdAt}\``,
      `- 更新: \`${updatedAt}\``,
      "- 状態: `参考`"
    ].join("\n");

    expect(validateMarkdownDocument("docs/reference.md", lateMetadata)).toContain(
      "先頭15行以内に作成がありません"
    );

    const reversed = markdown({
      created: updatedAt,
      updated: createdAt,
      status: "参考"
    });
    expect(validateMarkdownDocument("docs/reference.md", reversed)).toContain(
      "更新は作成以後でなければなりません"
    );
  });

  test("rejects impossible calendar dates and out-of-range times", () => {
    const impossibleDate = markdown({
      created: "2026-02-30T12:00:00+09:00",
      updated: updatedAt,
      status: "参考"
    });
    const impossibleTime = markdown({
      created: createdAt,
      updated: "2026-07-16T24:00:00+09:00",
      status: "参考"
    });

    expect(validateMarkdownDocument("docs/reference.md", impossibleDate)).toContain(
      "作成は YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください"
    );
    expect(validateMarkdownDocument("docs/reference.md", impossibleTime)).toContain(
      "更新は YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください"
    );
  });

  test("enforces path-specific statuses", () => {
    expect(
      validateMarkdownDocument(
        "docs/decisions/0001-local-first.md",
        markdown({ created: createdAt, updated: updatedAt, status: "参考" })
      )
    ).toContain("docs/decisions/ の状態は設計判断でなければなりません");

    expect(
      validateMarkdownDocument(
        "docs/plans/active/reorganization.md",
        markdown({ created: createdAt, updated: updatedAt, status: "参考" })
      )
    ).toContain("docs/plans/active/ の状態は実装計画でなければなりません");
  });
});

describe("HTML metadata validation", () => {
  test("accepts required head metadata", () => {
    const html = `<!doctype html>
<html>
  <head>
    <meta name="created-at" content="${createdAt}">
    <meta name="updated-at" content="${updatedAt}">
    <meta name="document-status" content="参考">
  </head>
  <body>Reference</body>
</html>`;

    expect(validateHtmlDocument("docs/reference.html", html)).toEqual([]);
  });

  test("rejects missing and invalid HTML metadata", () => {
    const html = `<!doctype html>
<html>
  <head>
    <meta name="created-at" content="2026-07-16">
    <meta name="document-status" content="archive">
  </head>
</html>`;

    expect(validateHtmlDocument("docs/reference.html", html)).toEqual([
      "created-atは YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください",
      "updated-atがありません",
      "document-statusは 現行 / 設計判断 / 実装計画 / 検証記録 / 参考 のいずれかです"
    ]);
  });
});

describe("document timestamp updater", () => {
  test("formats timestamps in JST independently of the process timezone", () => {
    expect(formatJstTimestamp(new Date("2026-07-16T13:01:02Z"))).toBe(
      "2026-07-16T22:01:02+09:00"
    );
  });

  test("updates only updated-at by default", () => {
    const source = markdown({
      created: createdAt,
      updated: "2026-07-10T12:00:00+09:00",
      verified: "2026-07-11T12:00:00+09:00",
      status: "現行"
    });

    const result = updateMarkdownMetadata(source, {
      timestamp: updatedAt,
      verified: false
    });

    expect(result).toContain(`- 作成: \`${createdAt}\``);
    expect(result).toContain(`- 更新: \`${updatedAt}\``);
    expect(result).toContain("- 検証: `2026-07-11T12:00:00+09:00`");
    expect(result).toContain("- 状態: `現行`");
    expect(result).toContain("本文");
  });

  test("updates verification only when explicitly requested", () => {
    const source = markdown({
      created: createdAt,
      updated: "2026-07-10T12:00:00+09:00",
      verified: "2026-07-11T12:00:00+09:00",
      status: "現行"
    });

    const result = updateMarkdownMetadata(source, {
      timestamp: verifiedAt,
      verified: true
    });

    expect(result).toContain(`- 更新: \`${verifiedAt}\``);
    expect(result).toContain(`- 検証: \`${verifiedAt}\``);
  });

  test("refuses documents without an existing updated field", () => {
    expect(() =>
      updateMarkdownMetadata("# Missing\n\n- 作成: `2026-07-16T22:00:00+09:00`\n", {
        timestamp: updatedAt,
        verified: false
      })
    ).toThrow("更新メタデータがありません");
  });
});

function markdown({ created, updated, verified, status }) {
  return [
    "# Document",
    "",
    `- 作成: \`${created}\``,
    `- 更新: \`${updated}\``,
    ...(verified ? [`- 検証: \`${verified}\``] : []),
    `- 状態: \`${status}\``,
    "",
    "---",
    "",
    "本文"
  ].join("\n");
}

function write(root, relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}
