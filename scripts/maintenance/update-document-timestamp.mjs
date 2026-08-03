#!/usr/bin/env bun

import { readFile, writeFile } from "node:fs/promises";
import { relative, resolve } from "node:path";

const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/;

export function formatJstTimestamp(date = new Date()) {
  const jst = new Date(date.getTime() + 9 * 60 * 60 * 1000);
  return `${jst.toISOString().slice(0, 19)}+09:00`;
}

export function updateMarkdownMetadata(content, { timestamp, verified }) {
  if (!timestampPattern.test(timestamp) || Number.isNaN(Date.parse(timestamp))) {
    throw new Error("timestampは YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください");
  }

  let updated = false;
  let verificationUpdated = false;
  const next = content
    .split(/\r?\n/)
    .map((line) => {
      if (line.match(/^- 更新: `[^`]+`\s*$/)) {
        updated = true;
        return `- 更新: \`${timestamp}\``;
      }
      if (verified && line.match(/^- 検証: `[^`]+`\s*$/)) {
        verificationUpdated = true;
        return `- 検証: \`${timestamp}\``;
      }
      return line;
    })
    .join("\n");

  if (!updated) throw new Error("更新メタデータがありません");
  if (verified && !verificationUpdated) throw new Error("検証メタデータがありません");
  return next;
}

async function main() {
  const args = process.argv.slice(2);
  const verified = args.includes("--verified");
  const paths = args.filter((arg) => arg !== "--verified");
  if (paths.length === 0) {
    throw new Error(
      "使用法: bun scripts/maintenance/update-document-timestamp.mjs [--verified] <path...>"
    );
  }

  const root = process.cwd();
  const timestamp = formatJstTimestamp();
  for (const path of paths) {
    const absolutePath = resolve(root, path);
    const relativePath = relative(root, absolutePath);
    if (relativePath.startsWith("..") || relativePath === "") {
      throw new Error(`Repo内のMarkdownを指定してください: ${path}`);
    }
    if (!relativePath.toLowerCase().endsWith(".md")) {
      throw new Error(`Markdown以外は更新できません: ${path}`);
    }
    if (
      relativePath.startsWith("docs/archive/") ||
      relativePath.startsWith("docs/local-archive/")
    ) {
      throw new Error(`archiveは更新対象外です: ${path}`);
    }

    const source = await readFile(absolutePath, "utf-8");
    const next = updateMarkdownMetadata(source, { timestamp, verified });
    if (next !== source) {
      await writeFile(absolutePath, next, "utf-8");
    }
    console.log(`${relativePath}: 更新=${timestamp}${verified ? " 検証=" + timestamp : ""}`);
  }
}

if (import.meta.main) {
  await main();
}
