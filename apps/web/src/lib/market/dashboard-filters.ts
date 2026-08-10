import type { Category, DataQuality, ScannerRowDTO } from "$lib/generated/scanner-snapshot";

export const dashboardCategories = ["WATCH", "CAUTION", "NO_TRADE", "LOW_PRIORITY"] as const;
export const dashboardCategoryFilters = ["ALL", ...dashboardCategories] as const;
export const dashboardRankingTimeframes = ["5m", "15m", "1h", "4h", "24h", "74h"] as const;
export const dashboardDataQualities = ["OK", "STALE", "MISSING", "PARTIAL"] as const;
export const dashboardViewModes = [
  { id: "standard", label: "標準" },
  { id: "watch", label: "注視のみ" },
  { id: "surge", label: "急騰" },
  { id: "drop", label: "急落" },
  { id: "turnover", label: "高売買代金" },
  { id: "quality", label: "低品質除外" }
] as const;
export const dashboardRankingMetrics = [
  ["上昇順", "changeUp"],
  ["下落順", "changeDown"],
  ["売買代金", "turnoverTop"],
  ["15m量倍率", "volumeUp"]
] as const;
export const dashboardRawSortKeys = [
  { id: "changePct", label: "価格変化" },
  { id: "turnoverUsdt", label: "売買代金" },
  { id: "volumeRatio", label: "15m量倍率" },
  { id: "attentionScore", label: "注目度" },
  { id: "riskTagCount", label: "警戒数" },
  { id: "dataQuality", label: "データ品質" }
] as const;
export const dashboardRawSortDirections = [
  { id: "desc", label: "大きい順" },
  { id: "asc", label: "小さい順" }
] as const;

export type DashboardCategoryFilter = (typeof dashboardCategoryFilters)[number];
export type DashboardRankingTimeframe = (typeof dashboardRankingTimeframes)[number];
export type DashboardViewMode = (typeof dashboardViewModes)[number]["id"];
export type DashboardRawSortKey = (typeof dashboardRawSortKeys)[number]["id"];
export type DashboardRawSortDirection = (typeof dashboardRawSortDirections)[number]["id"];

export type DashboardRawSortState = {
  sortKey: DashboardRawSortKey;
  direction: DashboardRawSortDirection;
};
export type EditableDashboardViewMode = Exclude<DashboardViewMode, "standard">;
export type DashboardViewSettings = {
  schemaVersion: 1;
  updatedAt: string;
  views: DashboardViewSettingsViews;
};
export type DashboardViewSettingsViews = {
  watch: CategoryInDashboardViewRule;
  surge: ChangePctAtLeastDashboardViewRule;
  drop: ChangePctAtMostNegativeDashboardViewRule;
  turnover: TurnoverAtLeastDashboardViewRule;
  quality: DataQualityInDashboardViewRule;
};
export type DashboardViewRule = DashboardViewSettingsViews[EditableDashboardViewMode];
export type CategoryInDashboardViewRule = {
  kind: "categoryIn";
  categories: Category[];
};
export type ChangePctAtLeastDashboardViewRule = {
  kind: "changePctAtLeast";
  thresholdPctByTimeframe: Record<DashboardRankingTimeframe, number>;
  excludedCategories: Category[];
};
export type ChangePctAtMostNegativeDashboardViewRule = {
  kind: "changePctAtMostNegative";
  thresholdPctByTimeframe: Record<DashboardRankingTimeframe, number>;
  excludedCategories: Category[];
};
export type TurnoverAtLeastDashboardViewRule = {
  kind: "turnoverAtLeast";
  thresholdUsdtByTimeframe: Record<DashboardRankingTimeframe, number>;
  excludedCategories: Category[];
};
export type DataQualityInDashboardViewRule = {
  kind: "dataQualityIn";
  allowedDataQualities: DataQuality[];
  excludedCategories: Category[];
};

const defaultTurnoverThresholdByTimeframe: Record<DashboardRankingTimeframe, number> = {
  "5m": 10_000,
  "15m": 50_000,
  "1h": 100_000,
  "4h": 300_000,
  "24h": 1_000_000,
  "74h": 2_000_000
};

const defaultChangePctThresholdByTimeframe: Record<DashboardRankingTimeframe, number> = {
  "5m": 2,
  "15m": 2,
  "1h": 2,
  "4h": 2,
  "24h": 2,
  "74h": 2
};

export const defaultDashboardViewSettings: DashboardViewSettings = {
  schemaVersion: 1,
  updatedAt: "1970-01-01T00:00:00.000Z",
  views: {
    watch: {
      kind: "categoryIn",
      categories: ["WATCH"]
    },
    surge: {
      kind: "changePctAtLeast",
      thresholdPctByTimeframe: defaultChangePctThresholdByTimeframe,
      excludedCategories: ["NO_TRADE"]
    },
    drop: {
      kind: "changePctAtMostNegative",
      thresholdPctByTimeframe: defaultChangePctThresholdByTimeframe,
      excludedCategories: ["NO_TRADE"]
    },
    turnover: {
      kind: "turnoverAtLeast",
      thresholdUsdtByTimeframe: defaultTurnoverThresholdByTimeframe,
      excludedCategories: ["NO_TRADE"]
    },
    quality: {
      kind: "dataQualityIn",
      allowedDataQualities: ["OK"],
      excludedCategories: ["NO_TRADE"]
    }
  }
};

export function isDashboardCategoryFilter(value: string): value is DashboardCategoryFilter {
  return dashboardCategoryFilters.includes(value as DashboardCategoryFilter);
}

export function isDashboardViewMode(value: string): value is DashboardViewMode {
  return dashboardViewModes.some((view) => view.id === value);
}

export function isDashboardRankingTimeframe(value: string): value is DashboardRankingTimeframe {
  return dashboardRankingTimeframes.includes(value as DashboardRankingTimeframe);
}

export function isDashboardRawSortKey(value: string): value is DashboardRawSortKey {
  return dashboardRawSortKeys.some((item) => item.id === value);
}

export function isDashboardRawSortDirection(value: string): value is DashboardRawSortDirection {
  return dashboardRawSortDirections.some((item) => item.id === value);
}

export function isEditableDashboardViewMode(value: string): value is EditableDashboardViewMode {
  return isDashboardViewMode(value) && value !== "standard";
}

export function normalizeDashboardViewSettings(value: unknown): DashboardViewSettings {
  const source = isObject(value) ? value : {};
  const sourceViews = isObject(source.views) ? source.views : {};
  const normalized: DashboardViewSettings = {
    schemaVersion: 1,
    updatedAt: typeof source.updatedAt === "string" ? source.updatedAt : defaultDashboardViewSettings.updatedAt,
    views: {
      watch: normalizeCategoryInRule(sourceViews.watch, defaultDashboardViewSettings.views.watch),
      surge: normalizeChangePctAtLeastRule(sourceViews.surge, defaultDashboardViewSettings.views.surge),
      drop: normalizeChangePctAtMostNegativeRule(sourceViews.drop, defaultDashboardViewSettings.views.drop),
      turnover: normalizeTurnoverAtLeastRule(sourceViews.turnover, defaultDashboardViewSettings.views.turnover),
      quality: normalizeDataQualityInRule(sourceViews.quality, defaultDashboardViewSettings.views.quality)
    }
  };
  return cloneDashboardViewSettings(normalized);
}

export function dashboardViewSettingsWithUpdatedView(
  settings: DashboardViewSettings,
  viewId: EditableDashboardViewMode,
  view: DashboardViewRule,
  updatedAt = new Date()
): DashboardViewSettings {
  const next = normalizeDashboardViewSettings(settings);
  const normalizedView = normalizeDashboardViewRule(viewId, view);
  if (viewId === "watch") {
    next.views.watch = normalizedView as CategoryInDashboardViewRule;
  } else if (viewId === "surge") {
    next.views.surge = normalizedView as ChangePctAtLeastDashboardViewRule;
  } else if (viewId === "drop") {
    next.views.drop = normalizedView as ChangePctAtMostNegativeDashboardViewRule;
  } else if (viewId === "turnover") {
    next.views.turnover = normalizedView as TurnoverAtLeastDashboardViewRule;
  } else {
    next.views.quality = normalizedView as DataQualityInDashboardViewRule;
  }
  next.updatedAt = updatedAt.toISOString();
  return next;
}

export function dashboardViewSettingsWithResetView(
  settings: DashboardViewSettings,
  viewId: EditableDashboardViewMode,
  updatedAt = new Date()
): DashboardViewSettings {
  return dashboardViewSettingsWithUpdatedView(
    settings,
    viewId,
    defaultDashboardViewSettings.views[viewId],
    updatedAt
  );
}

export function dashboardViewSettingsWithResetAll(updatedAt = new Date()): DashboardViewSettings {
  return normalizeDashboardViewSettings({
    ...defaultDashboardViewSettings,
    updatedAt: updatedAt.toISOString()
  });
}

export function cloneDashboardViewSettings(settings: DashboardViewSettings): DashboardViewSettings {
  return {
    schemaVersion: 1,
    updatedAt: settings.updatedAt,
    views: {
      watch: cloneRule(settings.views.watch),
      surge: cloneRule(settings.views.surge),
      drop: cloneRule(settings.views.drop),
      turnover: cloneRule(settings.views.turnover),
      quality: cloneRule(settings.views.quality)
    }
  };
}

export function matchesDashboardView(
  row: ScannerRowDTO,
  {
    activeCategory,
    activeView,
    selectedTimeframe,
    settings = defaultDashboardViewSettings
  }: {
    activeCategory: DashboardCategoryFilter;
    activeView: DashboardViewMode;
    selectedTimeframe: DashboardRankingTimeframe;
    settings?: DashboardViewSettings;
  }
) {
  if (activeView === "standard") return activeCategory === "ALL" || row.category === activeCategory;
  if (activeView === "watch") return matchesCategoryInRule(row, settings.views.watch);
  if (activeView === "quality") return matchesDataQualityInRule(row, settings.views.quality);
  if (activeView === "surge") return matchesChangePctAtLeastRule(row, settings.views.surge, selectedTimeframe);
  if (activeView === "drop") return matchesChangePctAtMostNegativeRule(row, settings.views.drop, selectedTimeframe);
  if (activeView === "turnover") {
    return matchesTurnoverAtLeastRule(row, settings.views.turnover, selectedTimeframe);
  }
  return true;
}

function normalizeDashboardViewRule(
  viewId: EditableDashboardViewMode,
  view: DashboardViewRule
): DashboardViewRule {
  if (viewId === "watch") return normalizeCategoryInRule(view, defaultDashboardViewSettings.views.watch);
  if (viewId === "surge") return normalizeChangePctAtLeastRule(view, defaultDashboardViewSettings.views.surge);
  if (viewId === "drop") return normalizeChangePctAtMostNegativeRule(view, defaultDashboardViewSettings.views.drop);
  if (viewId === "turnover") return normalizeTurnoverAtLeastRule(view, defaultDashboardViewSettings.views.turnover);
  return normalizeDataQualityInRule(view, defaultDashboardViewSettings.views.quality);
}

function matchesCategoryInRule(row: ScannerRowDTO, rule: CategoryInDashboardViewRule) {
  return rule.categories.includes(row.category);
}

function matchesChangePctAtLeastRule(
  row: ScannerRowDTO,
  rule: ChangePctAtLeastDashboardViewRule,
  selectedTimeframe: DashboardRankingTimeframe
) {
  return (
    !rule.excludedCategories.includes(row.category) &&
    (row.changePctByTf?.[selectedTimeframe] ?? Number.NEGATIVE_INFINITY) >=
      rule.thresholdPctByTimeframe[selectedTimeframe]
  );
}

function matchesChangePctAtMostNegativeRule(
  row: ScannerRowDTO,
  rule: ChangePctAtMostNegativeDashboardViewRule,
  selectedTimeframe: DashboardRankingTimeframe
) {
  return (
    !rule.excludedCategories.includes(row.category) &&
    (row.changePctByTf?.[selectedTimeframe] ?? Number.POSITIVE_INFINITY) <=
      -rule.thresholdPctByTimeframe[selectedTimeframe]
  );
}

function matchesTurnoverAtLeastRule(
  row: ScannerRowDTO,
  rule: TurnoverAtLeastDashboardViewRule,
  selectedTimeframe: DashboardRankingTimeframe
) {
  return (
    !rule.excludedCategories.includes(row.category) &&
    (row.turnoverUsdtByTf?.[selectedTimeframe] ?? 0) >= rule.thresholdUsdtByTimeframe[selectedTimeframe]
  );
}

function matchesDataQualityInRule(row: ScannerRowDTO, rule: DataQualityInDashboardViewRule) {
  return (
    !rule.excludedCategories.includes(row.category) &&
    rule.allowedDataQualities.includes(row.dataQuality)
  );
}

function normalizeCategoryInRule(value: unknown, fallback: CategoryInDashboardViewRule): CategoryInDashboardViewRule {
  if (!isObject(value) || value.kind !== "categoryIn") return cloneRule(fallback);
  const categories = normalizeNonEmptyCategoryArray(value.categories, fallback.categories);
  return { kind: "categoryIn", categories };
}

function normalizeChangePctAtLeastRule(
  value: unknown,
  fallback: ChangePctAtLeastDashboardViewRule
): ChangePctAtLeastDashboardViewRule {
  if (!isObject(value) || value.kind !== "changePctAtLeast") return cloneRule(fallback);
  return {
    kind: "changePctAtLeast",
    thresholdPctByTimeframe: normalizeThresholds(value.thresholdPctByTimeframe, fallback.thresholdPctByTimeframe),
    excludedCategories: normalizeCategoryArray(value.excludedCategories, fallback.excludedCategories)
  };
}

function normalizeChangePctAtMostNegativeRule(
  value: unknown,
  fallback: ChangePctAtMostNegativeDashboardViewRule
): ChangePctAtMostNegativeDashboardViewRule {
  if (!isObject(value) || value.kind !== "changePctAtMostNegative") return cloneRule(fallback);
  return {
    kind: "changePctAtMostNegative",
    thresholdPctByTimeframe: normalizeThresholds(value.thresholdPctByTimeframe, fallback.thresholdPctByTimeframe),
    excludedCategories: normalizeCategoryArray(value.excludedCategories, fallback.excludedCategories)
  };
}

function normalizeTurnoverAtLeastRule(
  value: unknown,
  fallback: TurnoverAtLeastDashboardViewRule
): TurnoverAtLeastDashboardViewRule {
  if (!isObject(value) || value.kind !== "turnoverAtLeast") return cloneRule(fallback);
  return {
    kind: "turnoverAtLeast",
    thresholdUsdtByTimeframe: normalizeThresholds(value.thresholdUsdtByTimeframe, fallback.thresholdUsdtByTimeframe),
    excludedCategories: normalizeCategoryArray(value.excludedCategories, fallback.excludedCategories)
  };
}

function normalizeDataQualityInRule(
  value: unknown,
  fallback: DataQualityInDashboardViewRule
): DataQualityInDashboardViewRule {
  if (!isObject(value) || value.kind !== "dataQualityIn") return cloneRule(fallback);
  return {
    kind: "dataQualityIn",
    allowedDataQualities: normalizeNonEmptyDataQualityArray(
      value.allowedDataQualities,
      fallback.allowedDataQualities
    ),
    excludedCategories: normalizeCategoryArray(value.excludedCategories, fallback.excludedCategories)
  };
}

function normalizeThresholds(
  value: unknown,
  fallback: Record<DashboardRankingTimeframe, number>
): Record<DashboardRankingTimeframe, number> {
  const source = isObject(value) ? value : {};
  return Object.fromEntries(
    dashboardRankingTimeframes.map((timeframe) => [
      timeframe,
      normalizeNonNegativeFiniteNumber(source[timeframe], fallback[timeframe])
    ])
  ) as Record<DashboardRankingTimeframe, number>;
}

function normalizeNonNegativeFiniteNumber(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : fallback;
}

function normalizeNonEmptyCategoryArray(value: unknown, fallback: Category[]) {
  const categories = normalizeCategoryArray(value, fallback);
  return categories.length > 0 ? categories : [...fallback];
}

function normalizeCategoryArray(value: unknown, fallback: Category[]) {
  if (!Array.isArray(value)) return [...fallback];
  const categories = value.filter((item): item is Category =>
    dashboardCategories.includes(item as Category)
  );
  return Array.from(new Set(categories));
}

function normalizeNonEmptyDataQualityArray(value: unknown, fallback: DataQuality[]) {
  if (!Array.isArray(value)) return [...fallback];
  const qualities = value.filter((item): item is DataQuality =>
    dashboardDataQualities.includes(item as DataQuality)
  );
  const unique = Array.from(new Set(qualities));
  return unique.length > 0 ? unique : [...fallback];
}

function cloneRule<T extends DashboardViewRule>(rule: T): T {
  return JSON.parse(JSON.stringify(rule)) as T;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
