import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

export function workingTreePaths(root) {
  const output = execFileSync(
    "git",
    ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
    {
      cwd: root,
      encoding: "utf-8"
    }
  );

  return [...new Set(output.split("\0").filter(Boolean))]
    .filter((path) => existsSync(resolve(root, path)))
    .sort();
}
