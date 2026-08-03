#!/usr/bin/env bun

import { stat } from "node:fs/promises";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { isDocumentTarget } from "./check-document-metadata.mjs";
import { workingTreePaths } from "./document-paths.mjs";

export function extractLocalLinks(path, content) {
  const links = [];
  const normalizedPath = path.toLowerCase();
  if (normalizedPath.endsWith(".html")) {
    for (const match of content.matchAll(/\b(?:href|src)=["']([^"']+)["']/gi)) {
      if (isLocalLink(match[1])) links.push(match[1]);
    }
    return links;
  }

  let fence = null;
  for (const line of content.split(/\r?\n/)) {
    const fenceMatch = line.match(/^\s*(```+|~~~+)/);
    if (fenceMatch) {
      fence = fence === null ? fenceMatch[1][0] : fence === fenceMatch[1][0] ? null : fence;
      continue;
    }
    if (fence !== null) continue;

    const withoutInlineCode = line.replace(/`[^`]*`/g, "");
    for (const match of withoutInlineCode.matchAll(/!?\[[^\]]*]\(([^)]+)\)/g)) {
      const destination = markdownDestination(match[1]);
      if (isLocalLink(destination)) links.push(destination);
    }
    for (const match of withoutInlineCode.matchAll(/\b(?:href|src)=["']([^"']+)["']/gi)) {
      if (isLocalLink(match[1])) links.push(match[1]);
    }
  }
  return links;
}

export async function checkDocumentLinks({ root = process.cwd(), paths } = {}) {
  const candidates = paths ?? workingTreePaths(root);
  const failures = [];

  for (const path of candidates.filter(isDocumentTarget).sort()) {
    const sourcePath = resolve(root, path);
    const content = await Bun.file(sourcePath).text();
    for (const link of extractLocalLinks(path, content)) {
      const target = localTarget(link);
      const resolvedTarget = resolve(dirname(sourcePath), target);
      if (!isInsideRoot(root, resolvedTarget)) {
        failures.push(`${path}: local link escapes repository: ${link}`);
        continue;
      }
      if (!(await exists(resolvedTarget))) {
        failures.push(`${path}: local link target does not exist: ${link}`);
      }
    }
  }

  return failures;
}

async function main() {
  const failures = await checkDocumentLinks({
    paths: process.argv.length > 2 ? process.argv.slice(2) : undefined
  });
  if (failures.length > 0) {
    console.error(failures.join("\n"));
    process.exitCode = 1;
    return;
  }
  console.log("document links: OK");
}

function markdownDestination(raw) {
  const trimmed = raw.trim();
  if (trimmed.startsWith("<") && trimmed.includes(">")) {
    return trimmed.slice(1, trimmed.indexOf(">"));
  }
  return trimmed.split(/\s+/, 1)[0];
}

function isLocalLink(value) {
  const trimmed = value.trim();
  return (
    trimmed.length > 0 &&
    !trimmed.startsWith("#") &&
    !trimmed.startsWith("//") &&
    !/^[a-z][a-z0-9+.-]*:/i.test(trimmed)
  );
}

function localTarget(link) {
  const withoutFragment = link.split("#", 1)[0].split("?", 1)[0];
  try {
    return decodeURIComponent(withoutFragment);
  } catch {
    return withoutFragment;
  }
}

function isInsideRoot(root, path) {
  const relativePath = relative(resolve(root), path);
  return (
    relativePath === "" ||
    (!relativePath.startsWith(`..${sep}`) && relativePath !== ".." && !isAbsolute(relativePath))
  );
}

async function exists(path) {
  try {
    await stat(path);
    return true;
  } catch (cause) {
    if (cause && typeof cause === "object" && "code" in cause && cause.code === "ENOENT") {
      return false;
    }
    throw cause;
  }
}

if (import.meta.main) {
  await main();
}
