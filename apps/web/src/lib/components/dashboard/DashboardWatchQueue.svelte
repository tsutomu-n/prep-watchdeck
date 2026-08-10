<script lang="ts">
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import type {
    DashboardRawSortState,
    DashboardRankingTimeframe,
    DashboardViewRule,
    DashboardViewSettings,
    EditableDashboardViewMode
  } from "$lib/market/dashboard-filters";
  import type { TickerOverlay, TickerPollController } from "$lib/market/ticker-overlay.svelte";
  import type { PastNote } from "$lib/past-note/past-note";
  import DashboardFilterRail from "$lib/components/dashboard/DashboardFilterRail.svelte";
  import DashboardWatchlist from "$lib/components/dashboard/DashboardWatchlist.svelte";

  let {
    rows,
    visibleRows,
    selectedSymbol,
    selectedTimeframe,
    rankingTimeframes,
    rawSortKeys,
    rawSortDirections,
    rawSortState,
    categoryFilters,
    viewModes,
    activeCategory,
    activeView,
    dataAsOf,
    generatedAt,
    pastNotes,
    viewSettings,
    viewSettingsDefaults,
    viewSettingsError,
    savingDashboardViewId,
    isRefreshing,
    refreshError,
    refreshNotice,
    tickerOverlay,
    tickerStatus,
    tickerError,
    volumeRatioBaseline,
    volumeRatioHelp,
    onCategorySelect,
    onViewSelect,
    onSymbolSelect,
    onTimeframeSelect,
    onRawSortKeyChange,
    onRawSortDirectionChange,
    onRawSortQuickSelect,
    onViewSettingsSave,
    onViewSettingsReset,
    onViewSettingsResetAll,
    onReload,
    onRefreshLive
  }: {
    rows: ScannerRowDTO[];
    visibleRows: ScannerRowDTO[];
    selectedSymbol: string | null;
    selectedTimeframe: DashboardRankingTimeframe;
    rankingTimeframes: readonly DashboardRankingTimeframe[];
    rawSortKeys: readonly { id: string; label: string }[];
    rawSortDirections: readonly { id: string; label: string }[];
    rawSortState: DashboardRawSortState;
    categoryFilters: readonly string[];
    viewModes: readonly { id: string; label: string }[];
    activeCategory: string;
    activeView: string;
    dataAsOf: number;
    generatedAt: number;
    pastNotes: PastNote[];
    viewSettings: DashboardViewSettings;
    viewSettingsDefaults: DashboardViewSettings;
    viewSettingsError: string | null;
    savingDashboardViewId: EditableDashboardViewMode | "all" | null;
    isRefreshing: boolean;
    refreshError: string | null;
    refreshNotice: string | null;
    tickerOverlay: TickerOverlay;
    tickerStatus: TickerPollController["status"];
    tickerError: string | null;
    volumeRatioBaseline: string;
    volumeRatioHelp: string;
    onCategorySelect: (category: string) => void;
    onViewSelect: (viewId: string) => void;
    onSymbolSelect: (symbol: string) => void;
    onTimeframeSelect: (timeframe: DashboardRankingTimeframe) => void;
    onRawSortKeyChange: (value: string) => void;
    onRawSortDirectionChange: (value: string) => void;
    onRawSortQuickSelect: (state: DashboardRawSortState) => void;
    onViewSettingsSave: (viewId: EditableDashboardViewMode, view: DashboardViewRule) => Promise<void>;
    onViewSettingsReset: (viewId: EditableDashboardViewMode) => Promise<void>;
    onViewSettingsResetAll: () => Promise<void>;
    onReload: () => void | Promise<void>;
    onRefreshLive: () => void | Promise<void>;
  } = $props();
</script>

<div class="queue-core">
  <DashboardFilterRail
    {rows}
    {categoryFilters}
    {activeCategory}
    {dataAsOf}
    {generatedAt}
    {isRefreshing}
    {refreshError}
    {refreshNotice}
    onCategorySelect={onCategorySelect}
    onReload={onReload}
    onRefreshLive={onRefreshLive}
  />

  <DashboardWatchlist
    {rows}
    {visibleRows}
    {selectedSymbol}
    {selectedTimeframe}
    {rankingTimeframes}
    {rawSortKeys}
    {rawSortDirections}
    {rawSortState}
    {viewModes}
    {activeCategory}
    {activeView}
    {pastNotes}
    {viewSettings}
    {viewSettingsDefaults}
    {viewSettingsError}
    {savingDashboardViewId}
    {tickerOverlay}
    {tickerStatus}
    {tickerError}
    {volumeRatioBaseline}
    {volumeRatioHelp}
    onViewSelect={onViewSelect}
    onSymbolSelect={onSymbolSelect}
    onTimeframeSelect={onTimeframeSelect}
    onRawSortKeyChange={onRawSortKeyChange}
    onRawSortDirectionChange={onRawSortDirectionChange}
    onRawSortQuickSelect={onRawSortQuickSelect}
    onViewSettingsSave={onViewSettingsSave}
    onViewSettingsReset={onViewSettingsReset}
    onViewSettingsResetAll={onViewSettingsResetAll}
  />
</div>

<style>
  .queue-core {
    display: grid;
    grid-template-columns: 1fr;
    align-items: start;
    gap: 8px;
  }
</style>
