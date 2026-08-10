<script lang="ts">
  import { tick } from "svelte";
  import type { Category, DataQuality, ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import {
    dashboardCategories,
    dashboardDataQualities,
    dashboardRankingTimeframes,
    type DashboardRankingTimeframe,
    type DashboardRawSortState,
    type DashboardViewRule,
    type DashboardViewSettings,
    type EditableDashboardViewMode
  } from "$lib/market/dashboard-filters";
  import { categoryLabel, dataQualityLabel } from "$lib/market/labels";
  import {
    fifteenMinuteVolumeRatioState,
    isFifteenMinuteVolumeRatioState,
    isQuickLensActive,
    rawSortQuickLenses,
    rawSortQuickTimeframes,
    rawSortStateForLens
  } from "$lib/market/raw-sort-presets";
  import type { TickerOverlay, TickerPollController } from "$lib/market/ticker-overlay.svelte";
  import type { PastNote } from "$lib/past-note/past-note";
  import DashboardMarketRow from "$lib/components/dashboard/DashboardMarketRow.svelte";

  let {
    rows,
    visibleRows,
    selectedSymbol,
    selectedTimeframe,
    rankingTimeframes,
    rawSortKeys,
    rawSortDirections,
    rawSortState,
    viewModes,
    activeCategory,
    activeView,
    pastNotes,
    viewSettings,
    viewSettingsDefaults,
    viewSettingsError,
    savingDashboardViewId,
    tickerOverlay,
    tickerStatus,
    tickerError,
    volumeRatioBaseline,
    volumeRatioHelp,
    onViewSelect,
    onSymbolSelect,
    onTimeframeSelect,
    onRawSortKeyChange,
    onRawSortDirectionChange,
    onRawSortQuickSelect,
    onViewSettingsSave,
    onViewSettingsReset,
    onViewSettingsResetAll
  }: {
    rows: ScannerRowDTO[];
    visibleRows: ScannerRowDTO[];
    selectedSymbol: string | null;
    selectedTimeframe: DashboardRankingTimeframe;
    rankingTimeframes: readonly DashboardRankingTimeframe[];
    rawSortKeys: readonly { id: string; label: string }[];
    rawSortDirections: readonly { id: string; label: string }[];
    rawSortState: DashboardRawSortState;
    viewModes: readonly { id: string; label: string }[];
    activeCategory: string;
    activeView: string;
    pastNotes: PastNote[];
    viewSettings: DashboardViewSettings;
    viewSettingsDefaults: DashboardViewSettings;
    viewSettingsError: string | null;
    savingDashboardViewId: EditableDashboardViewMode | "all" | null;
    tickerOverlay: TickerOverlay;
    tickerStatus: TickerPollController["status"];
    tickerError: string | null;
    volumeRatioBaseline: string;
    volumeRatioHelp: string;
    onViewSelect: (viewId: string) => void;
    onSymbolSelect: (symbol: string) => void;
    onTimeframeSelect: (timeframe: DashboardRankingTimeframe) => void;
    onRawSortKeyChange: (value: string) => void;
    onRawSortDirectionChange: (value: string) => void;
    onRawSortQuickSelect: (state: DashboardRawSortState) => void;
    onViewSettingsSave: (viewId: EditableDashboardViewMode, view: DashboardViewRule) => Promise<void>;
    onViewSettingsReset: (viewId: EditableDashboardViewMode) => Promise<void>;
    onViewSettingsResetAll: () => Promise<void>;
  } = $props();

  let activeViewLabel = $derived(viewModes.find((view) => view.id === activeView)?.label ?? "標準");
  let rawSortKeyLabel = $derived(
    rawSortKeys.find((item) => item.id === rawSortState.sortKey)?.label ?? rawSortState.sortKey
  );
  let rawSortDirectionLabel = $derived(
    rawSortDirections.find((item) => item.id === rawSortState.direction)?.label ?? rawSortState.direction
  );
  let watchCategoryDraft = $state<Category[]>([]);
  let qualityDraft = $state<DataQuality[]>([]);
  let surgeThresholdDraft = $state<Record<string, string>>({});
  let dropThresholdDraft = $state<Record<string, string>>({});
  let turnoverThresholdDraft = $state<Record<string, string>>({});
  let rowsElement = $state<HTMLDivElement | null>(null);
  let focusedRowSymbol = $state<string | null>(null);
  let rovingRowSymbol = $derived.by(() => {
    if (
      focusedRowSymbol !== null &&
      visibleRows.some((row) => row.symbol === focusedRowSymbol)
    ) {
      return focusedRowSymbol;
    }
    if (selectedSymbol !== null && visibleRows.some((row) => row.symbol === selectedSymbol)) {
      return selectedSymbol;
    }
    return visibleRows[0]?.symbol ?? null;
  });
  let tickerStatusLabel = $derived(
    tickerStatus === "live"
      ? "HOT LIVE"
      : tickerStatus === "retrying"
        ? "HOT RETRY"
        : tickerStatus === "paused"
          ? "HOT PAUSE"
          : "HOT WAIT"
  );
  let tickerStatusTitle = $derived(
    tickerError ??
      (tickerStatus === "live"
        ? "現在価格を1秒周期で更新中"
        : tickerStatus === "paused"
          ? "非表示中の価格更新を停止"
          : "現在価格の取得待ち")
  );

  $effect(() => {
    watchCategoryDraft = [...viewSettings.views.watch.categories];
    qualityDraft = [...viewSettings.views.quality.allowedDataQualities];
    surgeThresholdDraft = thresholdDraft(viewSettings.views.surge.thresholdPctByTimeframe);
    dropThresholdDraft = thresholdDraft(viewSettings.views.drop.thresholdPctByTimeframe);
    turnoverThresholdDraft = thresholdDraft(viewSettings.views.turnover.thresholdUsdtByTimeframe);
  });

  $effect(() => {
    if (
      focusedRowSymbol !== null &&
      !visibleRows.some((row) => row.symbol === focusedRowSymbol)
    ) {
      focusedRowSymbol = null;
    }
  });

  $effect(() => {
    activeCategory;
    activeView;
    viewSettings;
    if (rowsElement) rowsElement.scrollTop = 0;
  });

  function rowButton(symbol: string) {
    return Array.from(rowsElement?.querySelectorAll<HTMLButtonElement>("[data-row-select]") ?? []).find(
      (button) => button.dataset.symbol === symbol
    );
  }

  function scrollRowInsideList(target: HTMLButtonElement) {
    if (!rowsElement) return;
    const watchlist = rowsElement.closest<HTMLElement>(".watchlist");
    const scrollContainer = [rowsElement, watchlist].find((candidate) => {
      if (!candidate || candidate.scrollHeight <= candidate.clientHeight) return false;
      return ["auto", "scroll"].includes(getComputedStyle(candidate).overflowY);
    });
    if (!scrollContainer) return;

    const containerBox = scrollContainer.getBoundingClientRect();
    const targetBox = target.getBoundingClientRect();
    if (targetBox.top < containerBox.top) {
      scrollContainer.scrollTop -= containerBox.top - targetBox.top;
    } else if (targetBox.bottom > containerBox.bottom) {
      scrollContainer.scrollTop += targetBox.bottom - containerBox.bottom;
    }
  }

  function handleRowKeydown(symbol: string, event: KeyboardEvent) {
    const currentIndex = visibleRows.findIndex((row) => row.symbol === symbol);
    if (currentIndex < 0) return;

    let nextIndex: number;
    switch (event.key) {
      case "ArrowDown":
        nextIndex = Math.min(currentIndex + 1, visibleRows.length - 1);
        break;
      case "ArrowUp":
        nextIndex = Math.max(currentIndex - 1, 0);
        break;
      case "Home":
        nextIndex = 0;
        break;
      case "End":
        nextIndex = visibleRows.length - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    const nextSymbol = visibleRows[nextIndex]?.symbol;
    if (!nextSymbol) return;
    focusedRowSymbol = nextSymbol;
    void tick().then(() => {
      const target = rowButton(nextSymbol);
      target?.focus({ preventScroll: true });
      if (target) scrollRowInsideList(target);
    });
  }

  function handleRowsFocusOut(event: FocusEvent) {
    if (rowsElement?.contains(event.relatedTarget as Node | null)) return;
    focusedRowSymbol = null;
  }

  function pastNotesFor(symbol: string) {
    return pastNotes.filter((note) => note.symbol === symbol);
  }

  function hasAutoRekindleNote(symbol: string) {
    return pastNotesFor(symbol).some((note) => note.reason.includes("過去急変") || note.note.includes("過去急変"));
  }

  function pastNoteBadgeLabel(symbol: string) {
    const notes = pastNotesFor(symbol);
    if (notes.length === 0) return null;
    return hasAutoRekindleNote(symbol) ? "過去急変" : "銘柄注記";
  }

  function selectValue(event: Event) {
    return (event.currentTarget as HTMLSelectElement).value;
  }

  function selectQuickTimeframe(timeframe: (typeof rawSortQuickTimeframes)[number]) {
    onTimeframeSelect(timeframe);
  }

  function isTimeframeHeaderSortActive(timeframe: DashboardRankingTimeframe) {
    return selectedTimeframe === timeframe && rawSortState.sortKey === "changePct";
  }

  function selectTimeframeHeaderSort(timeframe: DashboardRankingTimeframe) {
    const direction =
      isTimeframeHeaderSortActive(timeframe) && rawSortState.direction === "desc" ? "asc" : "desc";
    onTimeframeSelect(timeframe);
    onRawSortQuickSelect({ sortKey: "changePct", direction });
  }

  function timeframeHeaderSortArrow(timeframe: DashboardRankingTimeframe) {
    if (!isTimeframeHeaderSortActive(timeframe)) return "";
    return rawSortState.direction === "desc" ? "↓" : "↑";
  }

  function selectQuickLens(lens: (typeof rawSortQuickLenses)[number]["id"]) {
    onRawSortQuickSelect(rawSortStateForLens(lens));
  }

  function thresholdDraft(source: Record<string, number>) {
    return Object.fromEntries(dashboardRankingTimeframes.map((timeframe) => [timeframe, String(source[timeframe])]));
  }

  function toggleDraftValue<T extends string>(source: T[], value: T, fallback: T[]) {
    const next = source.includes(value) ? source.filter((item) => item !== value) : [...source, value];
    return next.length > 0 ? next : [...fallback];
  }

  function toggleWatchCategory(category: Category) {
    watchCategoryDraft = toggleDraftValue(
      watchCategoryDraft,
      category,
      viewSettingsDefaults.views.watch.categories
    );
  }

  function toggleQuality(quality: DataQuality) {
    qualityDraft = toggleDraftValue(
      qualityDraft,
      quality,
      viewSettingsDefaults.views.quality.allowedDataQualities
    );
  }

  function setThresholdDraft(
    source: Record<string, string>,
    timeframe: string,
    value: string
  ) {
    return { ...source, [timeframe]: value };
  }

  function thresholdNumbers(source: Record<string, string>, fallback: Record<string, number>) {
    return Object.fromEntries(
      dashboardRankingTimeframes.map((timeframe) => {
        const parsed = Number(source[timeframe]);
        return [timeframe, Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback[timeframe]];
      })
    ) as Record<(typeof dashboardRankingTimeframes)[number], number>;
  }

  function saveWatchSettings() {
    return onViewSettingsSave("watch", {
      kind: "categoryIn",
      categories: watchCategoryDraft
    });
  }

  function saveQualitySettings() {
    return onViewSettingsSave("quality", {
      kind: "dataQualityIn",
      allowedDataQualities: qualityDraft,
      excludedCategories: viewSettings.views.quality.excludedCategories
    });
  }

  function saveSurgeSettings() {
    return onViewSettingsSave("surge", {
      kind: "changePctAtLeast",
      thresholdPctByTimeframe: thresholdNumbers(
        surgeThresholdDraft,
        viewSettingsDefaults.views.surge.thresholdPctByTimeframe
      ),
      excludedCategories: viewSettings.views.surge.excludedCategories
    });
  }

  function saveDropSettings() {
    return onViewSettingsSave("drop", {
      kind: "changePctAtMostNegative",
      thresholdPctByTimeframe: thresholdNumbers(
        dropThresholdDraft,
        viewSettingsDefaults.views.drop.thresholdPctByTimeframe
      ),
      excludedCategories: viewSettings.views.drop.excludedCategories
    });
  }

  function saveTurnoverSettings() {
    return onViewSettingsSave("turnover", {
      kind: "turnoverAtLeast",
      thresholdUsdtByTimeframe: thresholdNumbers(
        turnoverThresholdDraft,
        viewSettingsDefaults.views.turnover.thresholdUsdtByTimeframe
      ),
      excludedCategories: viewSettings.views.turnover.excludedCategories
    });
  }
</script>

<section class="watchlist" aria-label="精密監視リスト">
  <div class="section-head">
    <h2>精密監視リスト</h2>
    <span>{activeView === "standard" ? categoryLabel(activeCategory) : activeViewLabel}</span>
  </div>
  <div class="watch-toolbar">
    <div class="view-tabs" role="group" aria-label="ビュー">
      {#each viewModes as view}
        <button
          type="button"
          class:active={activeView === view.id}
          aria-pressed={activeView === view.id}
          onclick={() => onViewSelect(view.id)}
        >
          {view.label}
        </button>
      {/each}
    </div>
    <div class="raw-sort-controls" aria-label="Raw Sort">
      <span class="sort-state">
        Raw Sort: {selectedTimeframe} {rawSortKeyLabel} {rawSortDirectionLabel}
      </span>
      <div class="quick-sort-group" role="group" aria-label="時間軸ショートカット">
        {#each rawSortQuickTimeframes as timeframe}
          <button
            type="button"
            class:active={selectedTimeframe === timeframe}
            aria-pressed={selectedTimeframe === timeframe}
            onclick={() => selectQuickTimeframe(timeframe)}
          >
            {timeframe}
          </button>
        {/each}
      </div>
      <div class="quick-sort-group" role="group" aria-label="観点ショートカット">
        {#each rawSortQuickLenses as lens}
          <button
            type="button"
            class:active={isQuickLensActive(rawSortState, lens.id)}
            aria-pressed={isQuickLensActive(rawSortState, lens.id)}
            onclick={() => selectQuickLens(lens.id)}
          >
            {lens.label}
          </button>
        {/each}
        <button
          type="button"
          class:active={isFifteenMinuteVolumeRatioState(rawSortState)}
          aria-pressed={isFifteenMinuteVolumeRatioState(rawSortState)}
          onclick={() => onRawSortQuickSelect(fifteenMinuteVolumeRatioState)}
        >
          15m量倍率
        </button>
      </div>
      <details class="advanced-sort">
        <summary>詳細な並び替え</summary>
        <div class="advanced-sort-fields">
          <label>
            <span>キー</span>
            <select
              aria-label="Raw Sortキー"
              value={rawSortState.sortKey}
              onchange={(event) => onRawSortKeyChange(selectValue(event))}
            >
              {#each rawSortKeys as item}
                <option value={item.id}>{item.label}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>順序</span>
            <select
              aria-label="Raw Sort順序"
              value={rawSortState.direction}
              onchange={(event) => onRawSortDirectionChange(selectValue(event))}
            >
              {#each rawSortDirections as item}
                <option value={item.id}>{item.label}</option>
              {/each}
            </select>
          </label>
          <span class="sort-note">74h: 独自ルール用。72hではない。</span>
        </div>
      </details>
    </div>
    <span
      class:live={tickerStatus === "live"}
      class:retrying={tickerStatus === "retrying"}
      class:paused={tickerStatus === "paused"}
      class="ticker-state"
      title={tickerStatusTitle}
    >
      {tickerStatusLabel}
    </span>
    <strong>表示 {visibleRows.length} / 全 {rows.length}</strong>
  </div>
  <details class="view-settings" aria-busy={savingDashboardViewId !== null}>
    <summary>表示条件設定</summary>
    {#if viewSettingsError}
      <p class="settings-error" role="alert">{viewSettingsError}</p>
    {/if}
    {#if savingDashboardViewId !== null}
      <p id="view-settings-status" class="settings-status" role="status" aria-live="polite">
        表示条件を保存中です
      </p>
    {/if}
    <div class="settings-top-actions">
      <button type="button" disabled={savingDashboardViewId !== null} onclick={onViewSettingsResetAll}>
        全て既定値
      </button>
    </div>
    <div class="settings-grid">
      <section class="settings-card" aria-label="注視のみ表示条件">
        <header>
          <h3>注視のみ</h3>
          <div class="settings-actions">
            <button type="button" disabled={savingDashboardViewId !== null} onclick={saveWatchSettings}>
              保存
            </button>
            <button type="button" disabled={savingDashboardViewId !== null} onclick={() => onViewSettingsReset("watch")}>
              既定値
            </button>
          </div>
        </header>
        <div class="checkbox-grid">
          {#each dashboardCategories as category}
            <label>
              <input
                type="checkbox"
                checked={watchCategoryDraft.includes(category)}
                onchange={() => toggleWatchCategory(category)}
              />
              <span>{categoryLabel(category)}</span>
            </label>
          {/each}
        </div>
      </section>

      <section class="settings-card" aria-label="急騰表示条件">
        <header>
          <h3>急騰</h3>
          <div class="settings-actions">
            <button type="button" disabled={savingDashboardViewId !== null} onclick={saveSurgeSettings}>
              保存
            </button>
            <button type="button" disabled={savingDashboardViewId !== null} onclick={() => onViewSettingsReset("surge")}>
              既定値
            </button>
          </div>
        </header>
        <div class="threshold-grid">
          {#each rankingTimeframes as timeframe}
            <label>
              <span>{timeframe}</span>
              <input
                type="number"
                min="0"
                step="0.1"
                value={surgeThresholdDraft[timeframe]}
                aria-label={`急騰 ${timeframe} 閾値`}
                oninput={(event) =>
                  (surgeThresholdDraft = setThresholdDraft(
                    surgeThresholdDraft,
                    timeframe,
                    event.currentTarget.value
                  ))}
              />
            </label>
          {/each}
        </div>
      </section>

      <section class="settings-card" aria-label="急落表示条件">
        <header>
          <h3>急落</h3>
          <div class="settings-actions">
            <button type="button" disabled={savingDashboardViewId !== null} onclick={saveDropSettings}>
              保存
            </button>
            <button type="button" disabled={savingDashboardViewId !== null} onclick={() => onViewSettingsReset("drop")}>
              既定値
            </button>
          </div>
        </header>
        <div class="threshold-grid">
          {#each rankingTimeframes as timeframe}
            <label>
              <span>{timeframe}</span>
              <input
                type="number"
                min="0"
                step="0.1"
                value={dropThresholdDraft[timeframe]}
                aria-label={`急落 ${timeframe} 閾値`}
                oninput={(event) =>
                  (dropThresholdDraft = setThresholdDraft(
                    dropThresholdDraft,
                    timeframe,
                    event.currentTarget.value
                  ))}
              />
            </label>
          {/each}
        </div>
      </section>

      <section class="settings-card" aria-label="高売買代金表示条件">
        <header>
          <h3>高売買代金</h3>
          <div class="settings-actions">
            <button type="button" disabled={savingDashboardViewId !== null} onclick={saveTurnoverSettings}>
              保存
            </button>
            <button
              type="button"
              disabled={savingDashboardViewId !== null}
              onclick={() => onViewSettingsReset("turnover")}
            >
              既定値
            </button>
          </div>
        </header>
        <div class="threshold-grid">
          {#each rankingTimeframes as timeframe}
            <label>
              <span>{timeframe}</span>
              <input
                type="number"
                min="0"
                step="1000"
                value={turnoverThresholdDraft[timeframe]}
                aria-label={`高売買代金 ${timeframe} 閾値`}
                oninput={(event) =>
                  (turnoverThresholdDraft = setThresholdDraft(
                    turnoverThresholdDraft,
                    timeframe,
                    event.currentTarget.value
                  ))}
              />
            </label>
          {/each}
        </div>
      </section>

      <section class="settings-card" aria-label="低品質除外表示条件">
        <header>
          <h3>低品質除外</h3>
          <div class="settings-actions">
            <button type="button" disabled={savingDashboardViewId !== null} onclick={saveQualitySettings}>
              保存
            </button>
            <button type="button" disabled={savingDashboardViewId !== null} onclick={() => onViewSettingsReset("quality")}>
              既定値
            </button>
          </div>
        </header>
        <div class="checkbox-grid">
          {#each dashboardDataQualities as quality}
            <label>
              <input
                type="checkbox"
                checked={qualityDraft.includes(quality)}
                onchange={() => toggleQuality(quality)}
              />
              <span>{dataQualityLabel(quality)}</span>
            </label>
          {/each}
        </div>
      </section>
    </div>
  </details>
  <div class="market-header">
    <span>銘柄</span>
    <span>現在価格</span>
    <span>流れ</span>
    <span>監視材料</span>
    <span title={volumeRatioHelp}>15m量倍率<small>{volumeRatioBaseline}</small></span>
    {#each rankingTimeframes as timeframe}
      <button
        type="button"
        class:active={isTimeframeHeaderSortActive(timeframe)}
        aria-pressed={isTimeframeHeaderSortActive(timeframe)}
        aria-label={`${timeframe}価格変化で並び替え`}
        onclick={() => selectTimeframeHeaderSort(timeframe)}
      >
        <span>{timeframe}</span>
        <span class="sort-arrow" aria-hidden="true">{timeframeHeaderSortArrow(timeframe)}</span>
      </button>
    {/each}
    <span>{selectedTimeframe}代金</span>
    <span>品質</span>
    <span>注記</span>
  </div>
  <p id="watchlist-keyboard-help" class="sr-only">
    上下キーで銘柄を移動、EnterまたはSpaceで選択
  </p>
  <div
    class="rows"
    role="group"
    aria-label="銘柄選択"
    aria-describedby="watchlist-keyboard-help"
    bind:this={rowsElement}
    onfocusout={handleRowsFocusOut}
  >
    {#each visibleRows as row (row.symbol)}
      {@const noteBadge = pastNoteBadgeLabel(row.symbol)}
      <DashboardMarketRow
        {row}
        {tickerOverlay}
        {selectedSymbol}
        {selectedTimeframe}
        {rankingTimeframes}
        {noteBadge}
        {volumeRatioHelp}
        tabIndex={row.symbol === rovingRowSymbol ? 0 : -1}
        isRekindle={hasAutoRekindleNote(row.symbol)}
        {onSymbolSelect}
        onRowFocus={(symbol) => (focusedRowSymbol = symbol)}
        onRowKeydown={handleRowKeydown}
      />
    {:else}
      <p class="empty large">
        {activeView === "standard" ? categoryLabel(activeCategory) : activeViewLabel} に該当銘柄なし
      </p>
    {/each}
  </div>
</section>

<style>
  h2,
  p {
    margin: 0;
  }

  button {
    color: inherit;
    font: inherit;
    white-space: nowrap;
  }

  summary {
    white-space: nowrap;
  }

  .watchlist {
    container: watchlist / inline-size;
    min-height: 0;
    max-height: calc(100vh - 238px);
    overflow: auto;
    border: 1px solid color-mix(in srgb, var(--muted) 32%, transparent);
    background: var(--panel);
    box-shadow: none;
  }

  .section-head,
  .watch-toolbar {
    border-color: var(--line);
    background: var(--panel-strong);
  }

  .view-settings {
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel-solid);
  }

  .view-settings summary {
    position: sticky;
    top: 97px;
    z-index: 4;
    display: flex;
    align-items: center;
    justify-content: flex-start;
    gap: 10px;
    min-height: 34px;
    padding: 0 12px;
    border-bottom: 1px solid color-mix(in srgb, var(--muted) 18%, transparent);
    background: var(--panel-solid);
    color: var(--subtle);
    cursor: pointer;
    font-size: 12px;
    font-weight: 800;
  }

  .settings-top-actions button,
  .settings-actions button {
    min-height: 26px;
    border: 1px solid color-mix(in srgb, var(--muted) 38%, transparent);
    background: var(--surface);
    padding: 0 8px;
    color: var(--text);
    cursor: pointer;
    font-size: 11px;
    font-weight: 800;
  }

  .view-settings button:disabled {
    cursor: wait;
    opacity: 0.58;
  }

  .settings-error {
    padding: 10px 12px 0;
    color: var(--warning);
    font-size: 12px;
  }

  .settings-status {
    padding: 10px 12px 0;
    color: var(--subtle);
    font-size: 12px;
  }

  .settings-top-actions {
    display: flex;
    justify-content: flex-end;
    padding: 10px 12px 0;
  }

  .settings-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    padding: 10px 12px 12px;
  }

  .settings-card {
    border: 1px solid color-mix(in srgb, var(--muted) 24%, transparent);
    background: var(--panel-strong);
    padding: 10px;
  }

  .settings-card header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }

  .settings-card h3 {
    margin: 0;
    font-size: 12px;
  }

  .settings-actions {
    display: flex;
    gap: 6px;
  }

  .checkbox-grid,
  .threshold-grid {
    display: grid;
    gap: 6px;
  }

  .checkbox-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .checkbox-grid label,
  .threshold-grid label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    color: var(--subtle);
    font-size: 11px;
  }

  .checkbox-grid label {
    justify-content: flex-start;
  }

  .threshold-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .threshold-grid input {
    width: 78px;
    border: 1px solid color-mix(in srgb, var(--muted) 35%, transparent);
    background: var(--surface);
    padding: 4px 6px;
    color: var(--text);
    font: inherit;
    font-size: 11px;
  }

  .checkbox-grid input {
    accent-color: var(--focus);
  }

  .section-head {
    position: sticky;
    top: 0;
    z-index: 4;
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: 48px;
    padding: 0 12px;
    border-bottom: 1px solid var(--line-strong);
  }

  .section-head h2 {
    font-size: 16px;
  }

  .section-head span {
    color: var(--focus);
    font-size: 12px;
  }

  .watch-toolbar {
    position: sticky;
    top: 48px;
    z-index: 4;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--line-strong);
  }

  .watch-toolbar strong {
    color: var(--muted);
    font-size: 12px;
    white-space: nowrap;
  }

  .ticker-state {
    border-left: 2px solid var(--muted);
    padding-left: 7px;
    color: var(--muted);
    font-size: 10px;
    font-weight: 800;
    white-space: nowrap;
  }

  .ticker-state.live {
    border-color: var(--quality-good);
    color: var(--quality-good);
  }

  .ticker-state.retrying {
    border-color: var(--quality-risk);
    color: var(--quality-risk);
  }

  .ticker-state.paused {
    border-color: var(--warning-border);
    color: var(--warning);
  }

  .view-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .raw-sort-controls {
    display: flex;
    flex: 1 1 420px;
    flex-wrap: wrap;
    align-items: end;
    gap: 6px;
    min-width: 0;
  }

  .quick-sort-group {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
  }

  .quick-sort-group button {
    min-height: 28px;
    border: 1px solid color-mix(in srgb, var(--muted) 38%, transparent);
    background: color-mix(in srgb, var(--panel-selected) 90%, transparent);
    padding: 0 8px;
    color: var(--text);
    cursor: pointer;
    font: inherit;
    font-size: 11px;
    font-weight: 800;
  }

  .quick-sort-group button.active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .raw-sort-controls label {
    display: grid;
    gap: 2px;
    color: var(--subtle);
    font-size: 10px;
  }

  .raw-sort-controls select {
    min-height: 30px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: color-mix(in srgb, var(--panel-selected) 90%, transparent);
    color: var(--text);
    font: inherit;
    font-size: 12px;
    padding: 0 8px;
  }

  .raw-sort-controls select:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
    border-color: var(--focus);
  }

  .advanced-sort {
    align-self: center;
  }

  .advanced-sort summary {
    min-height: 28px;
    box-sizing: border-box;
    border: 1px solid color-mix(in srgb, var(--muted) 38%, transparent);
    background: var(--surface);
    padding: 6px 8px;
    color: var(--subtle);
    cursor: pointer;
    font-size: 11px;
    font-weight: 800;
    list-style-position: inside;
    white-space: nowrap;
  }

  .advanced-sort[open] {
    flex-basis: 100%;
    border-top: 1px solid color-mix(in srgb, var(--muted) 18%, transparent);
    padding-top: 6px;
  }

  .advanced-sort-fields {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 6px;
    padding-top: 6px;
  }

  .sort-state,
  .sort-note {
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.2;
  }

  .sort-state {
    align-self: center;
    color: var(--warning);
  }

  .view-tabs button {
    min-height: 30px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: color-mix(in srgb, var(--panel-selected) 90%, transparent);
    padding: 0 10px;
    color: var(--text);
    cursor: pointer;
    font: inherit;
  }

  .view-tabs button.active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
    font-weight: 800;
  }

  .market-header {
    position: sticky;
    top: 131px;
    z-index: 4;
    display: none;
    grid-template-columns:
      minmax(80px, 0.55fr)
      minmax(78px, 0.55fr)
      84px
      minmax(112px, 0.85fr)
      44px
      repeat(6, 46px)
      minmax(68px, 0.5fr)
      42px
      56px;
    gap: 10px;
    padding: 5px 12px;
    border-top: 1px solid color-mix(in srgb, var(--muted) 14%, transparent);
    background: var(--panel-solid);
    color: var(--muted);
    font-size: 10px;
    text-transform: uppercase;
  }

  .market-header > :nth-child(2),
  .market-header > :nth-child(n + 5) {
    text-align: right;
  }

  .market-header button {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 3px;
    min-width: 0;
    border: 0;
    background: transparent;
    color: inherit;
    cursor: pointer;
    font: inherit;
    line-height: 1.2;
    padding: 0;
    text-transform: inherit;
  }

  .market-header button:focus-visible {
    color: var(--text);
  }

  .market-header button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  .watchlist button:focus-visible,
  .watchlist summary:focus-visible,
  .watchlist input:focus-visible,
  .watchlist select:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  .watchlist button:active:not(:disabled),
  .watchlist summary:active {
    background: var(--panel-strong);
  }

  .watchlist .quick-sort-group button.active:active:not(:disabled),
  .watchlist .view-tabs button.active:active:not(:disabled) {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .market-header button.active {
    color: var(--focus);
    font-weight: 800;
  }

  .sort-arrow {
    display: inline-block;
    min-width: 8px;
    text-align: right;
  }

  .rows {
    display: grid;
  }

  @container watchlist (min-width: 62.125rem) {
    .market-header {
      display: grid;
    }
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  .empty {
    color: var(--subtle);
  }

  @media (max-width: 960px) {
    .watchlist {
      max-height: none;
      overflow: visible;
    }

    .section-head,
    .watch-toolbar,
    .view-settings summary,
    .market-header {
      position: static;
    }

    .market-header {
      display: none;
    }

    .rows {
      max-block-size: min(60svh, 36rem);
      overflow-y: auto;
      overscroll-behavior-y: auto;
      touch-action: pan-y;
      scroll-padding-block: 2px;
      padding-block-end: 2px;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .view-settings summary,
    .settings-top-actions button,
    .settings-actions button,
    .view-tabs button,
    .quick-sort-group button,
    .advanced-sort summary,
    .raw-sort-controls select,
    .threshold-grid input,
    .market-header button {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }

    .checkbox-grid label {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .settings-top-actions button:hover,
    .settings-actions button:hover,
    .quick-sort-group button:hover,
    .view-tabs button:hover,
    .market-header button:hover {
      border-color: var(--focus);
      color: var(--text);
    }
  }

  @media (max-width: 560px) {
    .watch-toolbar {
      align-items: stretch;
      flex-direction: column;
    }

    .raw-sort-controls {
      flex: 0 1 auto;
      align-items: center;
    }

    .advanced-sort,
    .advanced-sort[open] {
      width: 100%;
    }

    .advanced-sort-fields {
      align-items: stretch;
    }

    .advanced-sort-fields label {
      flex: 1 1 130px;
    }

    .advanced-sort-fields select {
      width: 100%;
    }

    .settings-grid {
      grid-template-columns: 1fr;
    }

    .threshold-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
