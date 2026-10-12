import { json } from "@sveltejs/kit";
import { isLocalhostRequest, LocalRequestError, readLocalJson } from "$lib/server/localhost-request";
import { createMarketArtifactRepository } from "$lib/server/market-artifact-repository";
import { RankingReader } from "$lib/server/ranking";
import {
  createUserWorkspaceRepository, isComparisonPin, isFavoriteTarget, isSavedView, UserWorkspaceError,
  type FavoriteTarget, type SavedView
} from "$lib/server/user-workspace-repository";
import type { RequestEvent } from "./$types";

const headers = { "cache-control": "no-store" };

export async function GET(event: RequestEvent) {
  if (!await isLocalhostRequest(event)) return fail(403, "localhost_required");
  try {
    return json(await createUserWorkspaceRepository().read(), { headers });
  } catch (cause) { return failure(cause); }
}

export async function POST(event: RequestEvent) {
  try {
    const payload = await readLocalJson(event);
    const value = record(payload);
    const repository = createUserWorkspaceRepository();
    if (value.action === "setFavorite" && isFavoriteTarget(value.target) &&
        typeof value.enabled === "boolean" &&
        keys(value, ["action", "target", "enabled"])) {
      if (value.enabled) await assertCurrent(value.target);
      return json(await repository.setFavorite(value.target, value.enabled), { headers });
    }
    if (value.action === "reconfirmFavorite" && keys(value, ["action", "target", "expectedRevision"]) &&
        isFavoriteTarget(value.target) && Number.isSafeInteger(value.expectedRevision)) {
      await assertCurrent(value.target);
      return json(await repository.setFavorite(value.target, true, value.expectedRevision as number), { headers });
    }
    if (value.action === "setPin" && keys(value, ["action", "pin", "enabled", "expectedRevision"]) &&
        isComparisonPin(value.pin) && typeof value.enabled === "boolean" &&
        Number.isSafeInteger(value.expectedRevision)) {
      if (value.enabled) await assertCurrent(value.pin.target);
      return json(await repository.setPin(value.pin, value.enabled, value.expectedRevision as number), { headers });
    }
    if (value.action === "saveView" && keys(value, ["action", "id", "name", "view", "expectedRevision"]) &&
        Number.isSafeInteger(value.expectedRevision)) {
      const view = { id: value.id, name: value.name, view: value.view } as SavedView;
      if (!isSavedView(view)) throw new LocalRequestError(400, "invalid_saved_view");
      return json(await repository.saveView(view, value.expectedRevision as number), { headers });
    }
    if (value.action === "removeView" && keys(value, ["action", "id", "expectedRevision"]) &&
        typeof value.id === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(value.id) &&
        Number.isSafeInteger(value.expectedRevision)) {
      return json(await repository.removeView(value.id, value.expectedRevision as number), { headers });
    }
    throw new LocalRequestError(400, "invalid_workspace_action");
  } catch (cause) { return failure(cause); }
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new LocalRequestError(400, "invalid_workspace_action");
  }
  return value as Record<string, unknown>;
}

function keys(value: Record<string, unknown>, allowed: string[]) {
  return Object.keys(value).length === allowed.length &&
    Object.keys(value).every((key) => allowed.includes(key));
}

async function assertCurrent(target: FavoriteTarget) {
  if (target.kind === "instrument") {
    const { universe } = await createMarketArtifactRepository().latest();
    const item = universe.items.find((entry) => entry.venueInstrumentId === target.id);
    if (!item?.active || item.venueInstrumentVersionId !== target.version) {
      throw new UserWorkspaceError(409, "favorite_instrument_changed");
    }
    return;
  }
  let ranking;
  try { ranking = await new RankingReader().read(new URLSearchParams()); }
  catch { throw new UserWorkspaceError(503, "favorite_reference_unavailable"); }
  const row = ranking.rows.find((entry) => entry.id === target.id);
  const referenceKey = row?.reference
    ? `${row.reference.provider}:${row.reference.symbol}:${row.reference.revision}` : null;
  const originals = row?.originals.map((entry) => `${entry.instrumentId}:${entry.versionId}`).sort();
  if (!row || row.mappingStatus !== "verified" || referenceKey !== target.referenceKey ||
      JSON.stringify(originals) !== JSON.stringify([...target.originals].sort())) {
    throw new UserWorkspaceError(409, "favorite_reference_changed");
  }
}

function fail(status: number, code: string) {
  return json({ error: code }, { status, headers });
}

function failure(cause: unknown) {
  if (cause instanceof LocalRequestError || cause instanceof UserWorkspaceError) {
    return fail(cause.status, cause.code);
  }
  return fail(500, "workspace_unavailable");
}
