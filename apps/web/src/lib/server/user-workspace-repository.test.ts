import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";
import { LocalFileUserWorkspaceRepository } from "./user-workspace-repository";

test("favorite operations merge under lock and saved views use revision CAS", async () => {
  const root = await mkdtemp(join(tmpdir(), "watchdeck-workspace-"));
  const path = join(root, "user-workspace.json");
  const repository = new LocalFileUserWorkspaceRepository(path);
  const a = { kind: "instrument" as const, id: "bitget:BTCUSDT", version: 1 };
  const b = { kind: "instrument" as const, id: "aster:ETHUSDT", version: 2 };
  try {
    expect((await repository.read()).revision).toBe(0);
    await Promise.all([repository.setFavorite(a, true), repository.setFavorite(b, true)]);
    const stored = await repository.read();
    expect(stored.favorites).toHaveLength(2);
    expect((await repository.setFavorite(a, true)).favorites).toHaveLength(2);
    const view = { id: "main", name: "監視", view: { mode: "reference", period: "24h" } };
    const saved = await repository.saveView(view, stored.revision);
    await expect(repository.saveView({ ...view, name: "古いタブ" }, stored.revision))
      .rejects.toMatchObject({ status: 409 });
    expect((await repository.removeView("main", saved.revision)).savedViews).toEqual([]);
    await writeFile(path, "{bad", "utf-8");
    await expect(repository.setFavorite(a, false)).rejects.toMatchObject({ status: 500 });
    expect(await readFile(path, "utf-8")).toBe("{bad");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
