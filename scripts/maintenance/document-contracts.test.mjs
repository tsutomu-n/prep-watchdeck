import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { checkDocumentLinks, extractLocalLinks } from "./check-document-links.mjs";
import { isDocumentTarget, validateMarkdownDocument } from "./check-document-metadata.mjs";
import { formatJstTimestamp, updateMarkdownMetadata } from "./update-document-timestamp.mjs";

const roots = [];
const createdAt = "2026-06-18T04:43:28+09:00";
const updatedAt = "2026-07-16T22:55:00+09:00";


afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});


describe("document contracts", () => {
  test("targets current human docs but ignores archives and generated paths", () => {
    expect(isDocumentTarget("README.md")).toBe(true);
    expect(isDocumentTarget("docs/current/overview.md")).toBe(true);
    expect(isDocumentTarget("docs/decisions/0012-product-evolution-boundary.md")).toBe(true);
    expect(isDocumentTarget("docs/archive/old.md")).toBe(false);
    expect(isDocumentTarget("apps/web/src/lib/generated/types.md")).toBe(false);
  });

  test("validates the metadata needed by current documents", () => {
    const valid = markdown({ verified: "2026-07-16T22:56:00+09:00", status: "現行" });
    expect(validateMarkdownDocument("docs/current/overview.md", valid)).toEqual([]);

    const invalid = markdown({ verified: null, status: "参考" });
    const errors = validateMarkdownDocument("docs/current/overview.md", invalid);
    expect(errors).toContain("docs/current/ では検証が必須です");
    expect(errors).toContain("docs/current/ の状態は現行でなければなりません");
  });

  test("updates timestamps in JST without rewriting creation metadata", () => {
    expect(formatJstTimestamp(new Date("2026-07-16T13:01:02Z"))).toBe(
      "2026-07-16T22:01:02+09:00"
    );
    const source = markdown({ verified: "2026-07-11T12:00:00+09:00", status: "現行" });
    const result = updateMarkdownMetadata(source, {
      timestamp: "2026-07-16T22:56:00+09:00",
      verified: true
    });
    expect(result).toContain(`- 作成: \`${createdAt}\``);
    expect(result).toContain("- 更新: `2026-07-16T22:56:00+09:00`");
    expect(result).toContain("- 検証: `2026-07-16T22:56:00+09:00`");
  });

  test("extracts local links while ignoring external, anchor, and fenced examples", () => {
    const content = `# Links\n\n[local](current/overview.md)\n[external](https://example.com)\n[anchor](#section)\n\n\`\`\`markdown\n[example](missing.md)\n\`\`\`\n\n<a href="../DESIGN.md">design</a>\n`;
    expect(extractLocalLinks("docs/README.md", content)).toEqual([
      "current/overview.md",
      "../DESIGN.md"
    ]);
  });

  test("reports a missing relative link with its source document", async () => {
    const root = fixtureRoot();
    write(root, "docs/README.md", "[missing](current/missing.md)\n");
    await expect(checkDocumentLinks({ root, paths: ["docs/README.md"] })).resolves.toEqual([
      "docs/README.md: local link target does not exist: current/missing.md"
    ]);
  });
});


function markdown({ verified, status }) {
  return [
    "# Document",
    "",
    `- 作成: \`${createdAt}\``,
    `- 更新: \`${updatedAt}\``,
    ...(verified ? [`- 検証: \`${verified}\``] : []),
    `- 状態: \`${status}\``,
    "",
    "---",
    "",
    "本文"
  ].join("\n");
}


function fixtureRoot() {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-doc-contract-"));
  roots.push(root);
  return root;
}


function write(root, relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}
