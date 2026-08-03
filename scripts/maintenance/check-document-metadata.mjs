#!/usr/bin/env bun

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { workingTreePaths } from "./document-paths.mjs";

const allowedStatuses = ["現行", "設計判断", "実装計画", "検証記録", "参考"];
const timestampPattern =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\+09:00$/;
const metadataLineLimit = 15;

export function isDocumentTarget(path) {
  const normalized = normalizePath(path);
  if (
    normalized.startsWith("docs/archive/") ||
    normalized.startsWith("docs/local-archive/") ||
    normalized.startsWith("mockups/") ||
    normalized.startsWith("var/") ||
    hasPathSegment(normalized, "node_modules") ||
    hasPathSegment(normalized, ".venv") ||
    hasPathSegment(normalized, ".svelte-kit") ||
    hasPathSegment(normalized, "generated") ||
    hasPathSegment(normalized, "test-results") ||
    hasPathSegment(normalized, "playwright-report")
  ) {
    return false;
  }

  if (
    normalized === "README.md" ||
    normalized === "DESIGN.md" ||
    normalized === "AGENTS.md"
  ) {
    return true;
  }
  if (normalized.startsWith("docs/") && /\.(md|html)$/i.test(normalized)) return true;
  return /^(apps|scripts|config)\/.+\/README\.md$/i.test(normalized);
}

export function validateMarkdownDocument(path, content) {
  const errors = [];
  const lines = content.split(/\r?\n/);
  const headerLines = lines.slice(0, metadataLineLimit);
  const firstContentLine = lines.find((line) => line.trim().length > 0);

  if (!firstContentLine?.startsWith("# ")) {
    errors.push("H1見出しがありません");
  }

  const metadata = parseMarkdownMetadata(headerLines);
  validateRequiredTimestamp(errors, metadata, "作成", "先頭15行以内に作成がありません");
  validateRequiredTimestamp(errors, metadata, "更新", "先頭15行以内に更新がありません");

  if (!metadata.has("状態")) {
    errors.push("先頭15行以内に状態がありません");
  } else if (!allowedStatuses.includes(metadata.get("状態"))) {
    errors.push(`状態は ${allowedStatuses.join(" / ")} のいずれかです`);
  }

  const normalizedPath = normalizePath(path);
  if (normalizedPath.startsWith("docs/current/")) {
    if (!metadata.has("検証")) {
      errors.push("docs/current/ では検証が必須です");
    } else if (!isTimestamp(metadata.get("検証"))) {
      errors.push("検証は YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください");
    }
    if (metadata.get("状態") !== "現行") {
      errors.push("docs/current/ の状態は現行でなければなりません");
    }
  }
  if (
    normalizedPath.startsWith("docs/decisions/") &&
    metadata.get("状態") !== "設計判断"
  ) {
    errors.push("docs/decisions/ の状態は設計判断でなければなりません");
  }
  if (
    normalizedPath.startsWith("docs/plans/active/") &&
    metadata.get("状態") !== "実装計画"
  ) {
    errors.push("docs/plans/active/ の状態は実装計画でなければなりません");
  }

  const created = metadata.get("作成");
  const updated = metadata.get("更新");
  if (isTimestamp(created) && isTimestamp(updated) && Date.parse(updated) < Date.parse(created)) {
    errors.push("更新は作成以後でなければなりません");
  }

  return unique(errors);
}

export function validateHtmlDocument(_path, content) {
  const errors = [];
  const created = readHtmlMeta(content, "created-at");
  const updated = readHtmlMeta(content, "updated-at");
  const status = readHtmlMeta(content, "document-status");

  if (created === undefined) {
    errors.push("created-atがありません");
  } else if (!isTimestamp(created)) {
    errors.push("created-atは YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください");
  }

  if (updated === undefined) {
    errors.push("updated-atがありません");
  } else if (!isTimestamp(updated)) {
    errors.push("updated-atは YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください");
  }

  if (status === undefined) {
    errors.push("document-statusがありません");
  } else if (!allowedStatuses.includes(status)) {
    errors.push(`document-statusは ${allowedStatuses.join(" / ")} のいずれかです`);
  }

  if (isTimestamp(created) && isTimestamp(updated) && Date.parse(updated) < Date.parse(created)) {
    errors.push("updated-atはcreated-at以後でなければなりません");
  }

  return errors;
}

export async function checkDocumentMetadata({ root = process.cwd(), paths } = {}) {
  const candidates = paths ?? workingTreePaths(root);
  const failures = [];

  for (const path of candidates.filter(isDocumentTarget).sort()) {
    const content = await readFile(resolve(root, path), "utf-8");
    const errors = path.toLowerCase().endsWith(".html")
      ? validateHtmlDocument(path, content)
      : validateMarkdownDocument(path, content);
    for (const error of errors) {
      failures.push(`${path}: ${error}`);
    }
  }

  return failures;
}

async function main() {
  const failures = await checkDocumentMetadata({
    paths: process.argv.length > 2 ? process.argv.slice(2) : undefined
  });
  if (failures.length > 0) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
    return;
  }
  console.log("document metadata: OK");
}

function validateRequiredTimestamp(errors, metadata, key, missingMessage) {
  if (!metadata.has(key)) {
    errors.push(missingMessage);
  } else if (!isTimestamp(metadata.get(key))) {
    errors.push(`${key}は YYYY-MM-DDTHH:mm:ss+09:00 形式で指定してください`);
  }
}

function parseMarkdownMetadata(lines) {
  const metadata = new Map();
  for (const line of lines) {
    const match = line.match(/^- (作成|更新|検証|状態): `([^`]+)`\s*$/);
    if (match) metadata.set(match[1], match[2]);
  }
  return metadata;
}

function readHtmlMeta(content, name) {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const forward = new RegExp(
    `<meta\\s+[^>]*name=["']${escapedName}["'][^>]*content=["']([^"']+)["'][^>]*>`,
    "i"
  );
  const reverse = new RegExp(
    `<meta\\s+[^>]*content=["']([^"']+)["'][^>]*name=["']${escapedName}["'][^>]*>`,
    "i"
  );
  return content.match(forward)?.[1] ?? content.match(reverse)?.[1];
}

function isTimestamp(value) {
  if (typeof value !== "string") return false;
  const match = value.match(timestampPattern);
  if (match === null) return false;

  const [, yearText, monthText, dayText, hourText, minuteText, secondText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > new Date(Date.UTC(year, month, 0)).getUTCDate() ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return false;
  }
  return !Number.isNaN(Date.parse(value));
}

function hasPathSegment(path, segment) {
  return path.split("/").includes(segment);
}

function normalizePath(path) {
  return path.replaceAll("\\", "/").replace(/^\.\//, "");
}

function unique(values) {
  return [...new Set(values)];
}

if (import.meta.main) {
  await main();
}
