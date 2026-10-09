import type { FavoriteTarget, UserWorkspace } from "$lib/server/user-workspace-repository";

export function favoriteKey(target: FavoriteTarget) {
  return target.kind === "instrument"
    ? `instrument:${target.id}:${target.version}`
    : `reference:${target.id}`;
}

export async function readUserWorkspace(): Promise<UserWorkspace> {
  const response = await fetch("/api/user-workspace", { cache: "no-store" });
  if (!response.ok) throw new Error("お気に入りを読み込めません");
  return await response.json() as UserWorkspace;
}

export async function setFavorite(target: FavoriteTarget, enabled: boolean): Promise<UserWorkspace> {
  const response = await fetch("/api/user-workspace", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "setFavorite", target, enabled })
  });
  if (!response.ok) throw new Error(response.status === 409
    ? "対象が更新されました。再確認してください。" : "お気に入りを保存できません");
  return await response.json() as UserWorkspace;
}

export async function reconfirmFavorite(target: FavoriteTarget, expectedRevision: number): Promise<UserWorkspace> {
  const response = await fetch("/api/user-workspace", { method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action: "reconfirmFavorite", target, expectedRevision }) });
  if (!response.ok) throw new Error(response.status === 409
    ? "対象または保存内容が更新されました。再確認してください。" : "お気に入りの確認を保存できません");
  return await response.json() as UserWorkspace;
}
