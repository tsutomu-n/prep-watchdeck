import { error, json } from "@sveltejs/kit";
import * as v from "valibot";
import {
  dashboardCategories,
  dashboardDataQualities,
  dashboardRankingTimeframes,
  dashboardViewSettingsWithResetAll,
  dashboardViewSettingsWithResetView,
  dashboardViewSettingsWithUpdatedView,
  defaultDashboardViewSettings,
  isEditableDashboardViewMode,
  type DashboardViewRule,
  type EditableDashboardViewMode
} from "$lib/market/dashboard-filters";
import { createDashboardViewSettingsRepository } from "$lib/server/dashboard-view-settings-repository";
import type { RequestEvent } from "./$types";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]"]);

const UpdateViewPayloadSchema = v.object({
  action: v.literal("update-view"),
  viewId: v.string(),
  view: v.unknown()
});
const ResetViewPayloadSchema = v.object({
  action: v.literal("reset-view"),
  viewId: v.string()
});
const ResetAllPayloadSchema = v.object({
  action: v.literal("reset-all")
});
const PatchPayloadSchema = v.union([UpdateViewPayloadSchema, ResetViewPayloadSchema, ResetAllPayloadSchema]);

export async function GET() {
  try {
    return json({
      settings: await createDashboardViewSettingsRepository().get(),
      defaults: defaultDashboardViewSettings
    });
  } catch (cause) {
    error(503, cause instanceof Error ? cause.message : "dashboard view settings unavailable");
  }
}

export async function PATCH(event: RequestEvent) {
  if (!LOCAL_HOSTS.has(event.url.hostname)) {
    error(403, "dashboard view settings are only available from localhost");
  }

  try {
    const payload: unknown = await event.request.json();
    const parsed = v.safeParse(PatchPayloadSchema, payload);
    if (!parsed.success) throw new Error("invalid dashboard view settings payload");

    const repo = createDashboardViewSettingsRepository();
    const current = await repo.get();
    const now = new Date();
    let settings;

    if (parsed.output.action === "reset-all") {
      settings = dashboardViewSettingsWithResetAll(now);
    } else {
      const viewId = parseEditableViewId(parsed.output.viewId);
      settings =
        parsed.output.action === "reset-view"
          ? dashboardViewSettingsWithResetView(current, viewId, now)
          : dashboardViewSettingsWithUpdatedView(current, viewId, parseViewRule(viewId, parsed.output.view), now);
    }

    return json({
      ok: true,
      settings: await repo.save(settings),
      defaults: defaultDashboardViewSettings
    });
  } catch (cause) {
    error(400, cause instanceof Error ? cause.message : "invalid dashboard view settings");
  }
}

function parseEditableViewId(value: string): EditableDashboardViewMode {
  if (!isEditableDashboardViewMode(value)) throw new Error("invalid viewId");
  return value;
}

function parseViewRule(viewId: EditableDashboardViewMode, value: unknown): DashboardViewRule {
  if (!isObject(value)) throw new Error("invalid view rule");
  if (viewId === "watch") return parseWatchRule(value);
  if (viewId === "surge") return parseSurgeRule(value);
  if (viewId === "drop") return parseDropRule(value);
  if (viewId === "turnover") return parseTurnoverRule(value);
  return parseQualityRule(value);
}

function parseWatchRule(value: Record<string, unknown>) {
  if (value.kind !== "categoryIn") throw new Error("invalid watch rule kind");
  return {
    kind: "categoryIn" as const,
    categories: parseCategories(value.categories, { nonEmpty: true })
  };
}

function parseSurgeRule(value: Record<string, unknown>) {
  if (value.kind !== "changePctAtLeast") throw new Error("invalid surge rule kind");
  return {
    kind: "changePctAtLeast" as const,
    thresholdPctByTimeframe: parseThresholds(value.thresholdPctByTimeframe, "thresholdPctByTimeframe"),
    excludedCategories: parseCategories(value.excludedCategories)
  };
}

function parseDropRule(value: Record<string, unknown>) {
  if (value.kind !== "changePctAtMostNegative") throw new Error("invalid drop rule kind");
  return {
    kind: "changePctAtMostNegative" as const,
    thresholdPctByTimeframe: parseThresholds(value.thresholdPctByTimeframe, "thresholdPctByTimeframe"),
    excludedCategories: parseCategories(value.excludedCategories)
  };
}

function parseTurnoverRule(value: Record<string, unknown>) {
  if (value.kind !== "turnoverAtLeast") throw new Error("invalid turnover rule kind");
  return {
    kind: "turnoverAtLeast" as const,
    thresholdUsdtByTimeframe: parseThresholds(value.thresholdUsdtByTimeframe, "thresholdUsdtByTimeframe"),
    excludedCategories: parseCategories(value.excludedCategories)
  };
}

function parseQualityRule(value: Record<string, unknown>) {
  if (value.kind !== "dataQualityIn") throw new Error("invalid quality rule kind");
  return {
    kind: "dataQualityIn" as const,
    allowedDataQualities: parseDataQualities(value.allowedDataQualities),
    excludedCategories: parseCategories(value.excludedCategories)
  };
}

function parseThresholds(value: unknown, field: string) {
  if (!isObject(value)) throw new Error(`invalid ${field}`);
  const keys = Object.keys(value);
  if (keys.some((key) => !dashboardRankingTimeframes.includes(key as never))) {
    throw new Error(`invalid ${field} timeframe`);
  }
  return Object.fromEntries(
    dashboardRankingTimeframes.map((timeframe) => {
      const threshold = value[timeframe];
      if (typeof threshold !== "number" || !Number.isFinite(threshold) || threshold < 0) {
        throw new Error(`invalid ${field} value`);
      }
      return [timeframe, threshold];
    })
  ) as Record<(typeof dashboardRankingTimeframes)[number], number>;
}

function parseCategories(value: unknown, options: { nonEmpty?: boolean } = {}) {
  if (!Array.isArray(value)) throw new Error("invalid categories");
  if (options.nonEmpty && value.length === 0) throw new Error("categories cannot be empty");
  if (value.some((item) => !dashboardCategories.includes(item as never))) {
    throw new Error("invalid category");
  }
  return Array.from(new Set(value)) as (typeof dashboardCategories)[number][];
}

function parseDataQualities(value: unknown) {
  if (!Array.isArray(value) || value.length === 0) throw new Error("allowedDataQualities cannot be empty");
  if (value.some((item) => !dashboardDataQualities.includes(item as never))) {
    throw new Error("invalid data quality");
  }
  return Array.from(new Set(value)) as (typeof dashboardDataQualities)[number][];
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
