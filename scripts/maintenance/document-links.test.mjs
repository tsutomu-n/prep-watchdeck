import { afterEach, describe, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  checkDocumentLinks,
  extractLocalLinks
} from "./check-document-links.mjs";

const roots = [];

afterEach(() => {
  for (const root of roots.splice(0)) {
    rmSync(root, { recursive: true, force: true });
  }
});

describe("document link extraction", () => {
  test("keeps local Markdown and HTML links while ignoring code, anchors, and external URLs", () => {
    const content = `# Links

[local](current/overview.md)
[with fragment](current/overview.md#role)
[external](https://example.com)
[anchor](#section)

\`\`\`markdown
[example only](missing.md)
\`\`\`

<a href="../DESIGN.md">design</a>
`;

    expect(extractLocalLinks("docs/README.md", content)).toEqual([
      "current/overview.md",
      "current/overview.md#role",
      "../DESIGN.md"
    ]);
  });
});

describe("document link checker", () => {
  test("accepts existing relative targets", async () => {
    const root = fixtureRoot();
    write(root, "README.md", "[docs](docs/README.md)\n");
    write(root, "docs/README.md", "[overview](current/overview.md)\n");
    write(root, "docs/current/overview.md", "# Overview\n");

    await expect(
      checkDocumentLinks({
        root,
        paths: ["README.md", "docs/README.md", "docs/current/overview.md"]
      })
    ).resolves.toEqual([]);
  });

  test("reports the source document and missing relative target", async () => {
    const root = fixtureRoot();
    write(root, "docs/README.md", "[missing](current/missing.md)\n");

    await expect(
      checkDocumentLinks({ root, paths: ["docs/README.md"] })
    ).resolves.toEqual([
      "docs/README.md: local link target does not exist: current/missing.md"
    ]);
  });

  test("does not audit archived documents", async () => {
    const root = fixtureRoot();
    write(root, "docs/archive/old.md", "[missing](missing.md)\n");

    await expect(
      checkDocumentLinks({ root, paths: ["docs/archive/old.md"] })
    ).resolves.toEqual([]);
  });
});

function fixtureRoot() {
  const root = mkdtempSync(join(tmpdir(), "prep-watchdeck-document-links-"));
  roots.push(root);
  return root;
}

function write(root, relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}
