<script lang="ts">
  import { invalidateAll } from "$app/navigation";
  import { untrack } from "svelte";
  import type { PageProps } from "./$types";
  import { isPastNote, type PastNote } from "$lib/past-note/past-note";
  import { savePastNoteRecord } from "$lib/past-note/past-note-client";
  import {
    dashboardCategoryFilters as categoryFilters,
    dashboardRawSortDirections as rawSortDirections,
    dashboardRawSortKeys as rawSortKeys,
    dashboardRankingMetrics as metrics,
    dashboardRankingTimeframes as rankingTimeframes,
    dashboardViewModes as viewModes,
    defaultDashboardViewSettings,
    isDashboardCategoryFilter,
    isDashboardRawSortDirection,
    isDashboardRawSortKey,
    isDashboardViewMode,
    matchesDashboardView,
    normalizeDashboardViewSettings,
    type DashboardViewRule,
    type DashboardViewSettings,
    type DashboardCategoryFilter as CategoryFilter,
    type DashboardRawSortState as RawSortState,
    type EditableDashboardViewMode,
    type DashboardRankingTimeframe as RankingTimeframe,
    type DashboardViewMode as ViewMode
  } from "$lib/market/dashboard-filters";
  import { formatCandidateRule74h } from "$lib/market/candidate-rule";
  import {
    formatVolumeRatioBaseline,
    formatVolumeRatioHelp
  } from "$lib/market/volume-ratio-meta";
  import { sortRowsByRawSort } from "$lib/market/raw-sort";
  import { rawSortStateForTimeframe } from "$lib/market/raw-sort-presets";
  import {
    buildSmartRankState,
    canRunSmartRank,
    smartRankCooldownRemainingSeconds,
    SMART_RANK_DEFAULT_TARGET_LIMIT,
    SMART_RANK_MAX_TARGET_LIMIT,
    type SmartRankState
  } from "$lib/market/smart-rank";
  import { range24h } from "$lib/market/row-analysis";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import {
    parseVpiLitePlusSummary,
    resolveVpiLitePlusRowItem
  } from "$lib/market/vpi-lite-plus";
  import {
    parseMarketComparisonSummary
  } from "$lib/market/market-comparison";
  import {
    findPerpVenueComparisonItem,
    parsePerpVenueComparisonSummary
  } from "$lib/market/perp-venue-comparison";
  import { shouldAutoRefreshDashboard } from "$lib/market/dashboard-refresh.svelte";
  import {
    TickerOverlay,
    TickerPollController,
    type TickerRuntimeBatch
  } from "$lib/market/ticker-overlay.svelte";
  import type { PrepWatchdeckScannerSnapshot } from "$lib/generated/scanner-snapshot";
  import {
    resolveDashboardSelection,
    validateDraftSymbol
  } from "$lib/market/dashboard-selection";
  import DashboardRankingArea from "$lib/components/dashboard/DashboardRankingArea.svelte";
  import DashboardMarketComparisonPanel from "$lib/components/dashboard/DashboardMarketComparisonPanel.svelte";
  import DashboardVpiExperimentPanel from "$lib/components/dashboard/DashboardVpiExperimentPanel.svelte";
  import DashboardWatchQueue from "$lib/components/dashboard/DashboardWatchQueue.svelte";
  import SelectedSymbolContext from "$lib/components/dashboard/SelectedSymbolContext.svelte";
  import SelectedSymbolOverview from "$lib/components/dashboard/SelectedSymbolOverview.svelte";
  import SelectedSymbolVpiDetail from "$lib/components/dashboard/SelectedSymbolVpiDetail.svelte";
  import SelectedSymbolVenueComparison from "$lib/components/dashboard/SelectedSymbolVenueComparison.svelte";
  import SmartRankControl from "$lib/components/dashboard/SmartRankControl.svelte";
  import DashboardTopbar from "$lib/components/dashboard/DashboardTopbar.svelte";

  const serviceRefreshIntervalMs = 60_000;
  const newerDraftSaveNotice = "送信時点の内容を保存しました。追加の変更は未保存です";
  type DraftSaveCompletion = "same-revision" | "newer-draft" | "stale";
  type MutationFeedback = {
    error: string | null;
    notice: string | null;
    missingFields: string[];
  };
  type PendingNoteDraftReset = {
    symbol: string;
    revision: number;
  };
  type RefreshLiveResponse = {
    ok?: boolean;
    message?: string;
    error?: string;
    fallback?: {
      message?: string;
    };
  };

  let { data }: PageProps = $props();

  let selectedSymbol = $state<string | null>(null);
  let activeCategory = $state<CategoryFilter>("ALL");
  let selectedTimeframe = $state<RankingTimeframe>("15m");
  let activeView = $state<ViewMode>("standard");
  let rawSortState = $state<RawSortState>({
    sortKey: "changePct",
    direction: "desc"
  });
  let smartRankTargetLimit = $state(String(SMART_RANK_DEFAULT_TARGET_LIMIT));
  let smartRankState = $state<SmartRankState | null>(null);
  let dashboardViewSettings = $state<DashboardViewSettings>(
    normalizeDashboardViewSettings(defaultDashboardViewSettings)
  );
  let dashboardViewSettingsDefaults = $state<DashboardViewSettings>(
    normalizeDashboardViewSettings(defaultDashboardViewSettings)
  );
  let dashboardViewSettingsError = $state<string | null>(null);
  let savingDashboardViewId = $state<EditableDashboardViewMode | "all" | null>(null);
  let pastNotes = $state<PastNote[]>([]);
  let noteReason = $state("");
  let noteText = $state("");
  let isSavingPastNote = $state(false);
  let noteFeedbackBySymbol = $state<Record<string, MutationFeedback>>({});
  let noteDraftSymbol = $state<string | null>(null);
  let noteDraftRevision = $state(0);
  let pendingNoteDraftReset = $state<PendingNoteDraftReset | null>(null);
  let isRefreshing = $state(false);
  let isAutoReloading = $state(false);
  let refreshError = $state<string | null>(null);
  let refreshNotice = $state<string | null>(null);
  let refreshNowMs = $state(Date.now());
  let refreshCycleStartedAtMs = $state(Date.now());
  let pageVisibility = $state<DocumentVisibilityState>("visible");
  let snapshot = $state(untrack(() => data.snapshot));
  let lastServerSnapshot = untrack(() => data.snapshot);
  let serviceState = $state(untrack(() => data.serviceState));
  let lastServerServiceState = untrack(() => data.serviceState);
  const tickerOverlay = new TickerOverlay();
  let tickerPollController = $state<TickerPollController | null>(null);
  let tickerStatus = $derived(tickerPollController?.status ?? "idle");
  let tickerError = $derived(tickerPollController?.lastError ?? null);
  let canCheckServiceSnapshot = $derived(
    snapshot?.summary?.serviceSource === "duckdb-service" && pageVisibility === "visible"
  );
  let nextServiceRefreshAtMs = $derived(
    canCheckServiceSnapshot ? refreshCycleStartedAtMs + serviceRefreshIntervalMs : null
  );
  let refreshSecondsRemaining = $derived(
    nextServiceRefreshAtMs === null
      ? null
      : Math.max(0, Math.ceil((nextServiceRefreshAtMs - refreshNowMs) / 1000))
  );
  let refreshProgressPct = $derived(
    nextServiceRefreshAtMs === null
      ? 0
      : (Math.max(0, refreshNowMs - refreshCycleStartedAtMs) / serviceRefreshIntervalMs) *
        100
  );
  let serverPastNotes = $derived((data.pastNotes ?? []).filter(isPastNote));
  let rows = $derived(snapshot?.rows ?? []);
  let filteredRows = $derived(
    rows.filter((row) =>
      matchesDashboardView(row, {
        activeCategory,
        activeView,
        selectedTimeframe,
        settings: dashboardViewSettings
      })
    )
  );
  let visibleRows = $derived(sortRowsByRawSort(filteredRows, rawSortState, selectedTimeframe));
  let selection = $derived(resolveDashboardSelection(selectedSymbol, visibleRows));
  let selected = $derived(selection.row);
  let candidateRuleText = $derived(
    formatCandidateRule74h(snapshot?.summary?.candidateRule74h)
  );
  let volumeRatioBaseline = $derived(
    formatVolumeRatioBaseline(snapshot?.summary?.volumeRatio15m)
  );
  let volumeRatioHelp = $derived(formatVolumeRatioHelp(snapshot?.summary?.volumeRatio15m));
  let vpiSummary = $derived(parseVpiLitePlusSummary(snapshot?.summary?.vpiLitePlus));
  let marketComparisonSummary = $derived(
    parseMarketComparisonSummary(snapshot?.summary?.marketComparison)
  );
  let perpVenueComparisonSummary = $derived(
    parsePerpVenueComparisonSummary(snapshot?.summary?.perpVenueComparison)
  );
  let selectedVpi = $derived(
    vpiSummary && selected
      ? resolveVpiLitePlusRowItem(vpiSummary, selected.symbol, selected.display?.vpiLitePlus)
      : null
  );
  let selectedVenueComparison = $derived(
    selected
      ? findPerpVenueComparisonItem(perpVenueComparisonSummary, selected.symbol)
      : null
  );
  let availableSymbols = $derived(rows.map((row) => row.symbol));
  let conflictingDraftSymbols = $derived(
    noteDraftSymbol && noteDraftSymbol !== selection.selectedSymbol ? [noteDraftSymbol] : []
  );
  let selectedPastNotes = $derived(selected ? pastNotesFor(selected.symbol) : []);
  let noteFeedback = $derived(
    mutationFeedbackFor(noteFeedbackBySymbol, selection.selectedSymbol)
  );
  let noteSaveError = $derived(noteFeedback.error);
  let pastNoteSaveNotice = $derived(noteFeedback.notice);
  let smartRankCooldownSeconds = $derived(smartRankCooldownRemainingSeconds(refreshNowMs, smartRankState));
  let isSmartRankRunnable = $derived(
    canRunSmartRank({ nowMs: refreshNowMs, state: smartRankState, availableRows: visibleRows.length })
  );

  $effect(() => {
    pastNotes = serverPastNotes;
  });

  $effect(() => {
    dashboardViewSettings = normalizeDashboardViewSettings(
      data.dashboardViewSettings ?? defaultDashboardViewSettings
    );
  });

  $effect(() => {
    const next = data.snapshot;
    if (next !== lastServerSnapshot) {
      lastServerSnapshot = next;
      snapshot = next;
      refreshNowMs = Date.now();
      refreshCycleStartedAtMs = refreshNowMs;
    }
    const nextServiceState = data.serviceState;
    if (nextServiceState !== lastServerServiceState) {
      lastServerServiceState = nextServiceState;
      serviceState = nextServiceState;
    }
  });

  $effect(() => {
    if (selectedSymbol !== null || selection.selectedSymbol === null) return;
    selectedSymbol = selection.selectedSymbol;
  });

  $effect(() => {
    const updateVisibility = () => {
      pageVisibility = document.visibilityState;
    };
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  });

  $effect(() => {
    const controller = new TickerPollController({
      overlay: tickerOverlay,
      fetchBatch: fetchTickerRuntimeBatch
    });
    tickerPollController = controller;
    controller.start();
    return () => {
      controller.stop();
      tickerPollController = null;
    };
  });

  $effect(() => {
    let timer: number | null = null;
    const startTimer = window.setTimeout(() => {
      refreshNowMs = Date.now();
      timer = window.setInterval(() => {
        refreshNowMs = Date.now();
      }, 1_000);
    }, 500);
    return () => {
      window.clearTimeout(startTimer);
      if (timer !== null) window.clearInterval(timer);
    };
  });

  $effect(() => {
    if (nextServiceRefreshAtMs === null) return;
    if (refreshNowMs < nextServiceRefreshAtMs) return;
    if (isRefreshing || isAutoReloading) return;
    void refreshServiceSnapshot();
  });

  function selectRankingTimeframe(timeframe: RankingTimeframe) {
    if (timeframe === selectedTimeframe) return;
    selectedTimeframe = timeframe;
    rawSortState = rawSortStateForTimeframe(rawSortState);
  }

  function pastNotesFor(symbol: string) {
    return pastNotes.filter((note) => note.symbol === symbol);
  }

  function mutationFeedbackFor(
    feedbackBySymbol: Record<string, MutationFeedback>,
    symbol: string | null
  ): MutationFeedback {
    return symbol
      ? (feedbackBySymbol[symbol] ?? { error: null, notice: null, missingFields: [] })
      : { error: null, notice: null, missingFields: [] };
  }

  function updateMutationFeedback(
    feedbackBySymbol: Record<string, MutationFeedback>,
    symbol: string | null,
    patch: Partial<MutationFeedback>
  ) {
    if (!symbol) return;
    feedbackBySymbol[symbol] = {
      ...mutationFeedbackFor(feedbackBySymbol, symbol),
      ...patch
    };
  }

  function clearMutationFeedback(
    feedbackBySymbol: Record<string, MutationFeedback>,
    symbol: string | null
  ) {
    if (!symbol) return;
    feedbackBySymbol[symbol] = { error: null, notice: null, missingFields: [] };
  }

  function markNoteDraftChanged() {
    const pendingReset = pendingNoteDraftReset;
    noteDraftRevision += 1;
    pendingNoteDraftReset = null;
    if (pendingReset) {
      updateMutationFeedback(noteFeedbackBySymbol, pendingReset.symbol, {
        notice: newerDraftSaveNotice
      });
      return;
    }

    const symbol = noteDraftSymbol ?? selection.selectedSymbol;
    const feedback = mutationFeedbackFor(noteFeedbackBySymbol, symbol);
    if (feedback.notice !== newerDraftSaveNotice) {
      clearMutationFeedback(noteFeedbackBySymbol, symbol);
    }
  }

  function clearNoteDraftIfUnchanged(reset: PendingNoteDraftReset) {
    if (noteDraftSymbol !== reset.symbol || noteDraftRevision !== reset.revision) {
      pendingNoteDraftReset = null;
      return;
    }
    noteReason = "";
    noteText = "";
    noteDraftSymbol = null;
    noteDraftRevision += 1;
    pendingNoteDraftReset = null;
  }

  function completeNoteDraftSave(symbol: string, revision: number): DraftSaveCompletion {
    const reset = { symbol, revision };
    if (noteDraftSymbol !== symbol) return "stale";
    if (noteDraftRevision !== revision) {
      return noteDraftRevision > revision ? "newer-draft" : "stale";
    }
    if (selection.selectedSymbol === symbol) {
      clearNoteDraftIfUnchanged(reset);
      return "same-revision";
    }
    pendingNoteDraftReset = reset;
    return "same-revision";
  }

  function applyPendingNoteDraftReset(symbol: string) {
    if (pendingNoteDraftReset?.symbol === symbol) {
      clearNoteDraftIfUnchanged(pendingNoteDraftReset);
    }
  }

  function captureNoteDraftSymbol() {
    if (noteDraftSymbol !== null || selection.selectedSymbol === null) return;
    noteDraftSymbol = selection.selectedSymbol;
  }

  function validateNoteDraftForSave() {
    const retainedSymbol = selection.selectedSymbol;
    const retainedSymbolExists =
      retainedSymbol !== null && availableSymbols.includes(retainedSymbol);
    return validateDraftSymbol({
      draftSymbol: noteDraftSymbol,
      displayedSymbol: retainedSymbolExists ? (selected?.symbol ?? null) : retainedSymbol,
      availableSymbols
    });
  }

  function noteDraftSaveError(
    validation: Exclude<ReturnType<typeof validateDraftSymbol>, { ok: true }>
  ) {
    if (validation.reason === "symbol-mismatch") {
      return `下書きは ${noteDraftSymbol ?? "未確定"} に固定されています。現在の銘柄には保存できません`;
    }
    if (validation.reason === "symbol-missing") {
      return `${noteDraftSymbol ?? "対象銘柄"} が現在のsnapshotにないため保存できません`;
    }
    return "保存対象の銘柄が表示上で確定していません";
  }

  function setNoteReason(value: string) {
    captureNoteDraftSymbol();
    markNoteDraftChanged();
    noteReason = value;
  }

  function setNoteText(value: string) {
    captureNoteDraftSymbol();
    markNoteDraftChanged();
    noteText = value;
  }

  function selectCategoryFilter(category: string) {
    if (!isDashboardCategoryFilter(category)) return;
    activeCategory = category;
  }

  function selectViewMode(viewId: string) {
    if (!isDashboardViewMode(viewId)) return;
    activeView = viewId;
  }

  function selectDashboardSymbol(symbol: string) {
    if (!availableSymbols.includes(symbol)) return;
    applyPendingNoteDraftReset(symbol);
    selectedSymbol = symbol;
  }

  function setRawSortKey(value: string) {
    if (!isDashboardRawSortKey(value)) return;
    if (value === "volumeRatio") {
      selectedTimeframe = "15m";
      rawSortState = { sortKey: value, direction: "desc" };
      return;
    }
    rawSortState = { ...rawSortState, sortKey: value };
  }

  function setRawSortDirection(value: string) {
    if (!isDashboardRawSortDirection(value)) return;
    rawSortState = { ...rawSortState, direction: value };
  }

  function setRawSortQuickSelect(state: RawSortState) {
    if (state.sortKey === "volumeRatio") selectedTimeframe = "15m";
    rawSortState = state;
  }

  function setSmartRankTargetLimit(value: string) {
    smartRankTargetLimit = value;
  }

  function runSmartRank() {
    if (!snapshot || !isSmartRankRunnable) return;
    smartRankState = buildSmartRankState({
      rows: visibleRows,
      snapshotRunId: snapshot.runId,
      timeframe: selectedTimeframe,
      rawSortState,
      categoryFilter: activeCategory,
      viewFilter: activeView,
      targetLimit: smartRankTargetLimit,
      nowMs: refreshNowMs
    });
  }

  async function saveDashboardViewSettingsView(viewId: EditableDashboardViewMode, view: DashboardViewRule) {
    await patchDashboardViewSettings({ action: "update-view", viewId, view }, viewId);
  }

  async function resetDashboardViewSettingsView(viewId: EditableDashboardViewMode) {
    await patchDashboardViewSettings({ action: "reset-view", viewId }, viewId);
  }

  async function resetAllDashboardViewSettings() {
    await patchDashboardViewSettings({ action: "reset-all" }, "all");
  }

  async function patchDashboardViewSettings(
    payload:
      | { action: "update-view"; viewId: EditableDashboardViewMode; view: DashboardViewRule }
      | { action: "reset-view"; viewId: EditableDashboardViewMode }
      | { action: "reset-all" },
    savingId: EditableDashboardViewMode | "all"
  ) {
    dashboardViewSettingsError = null;
    savingDashboardViewId = savingId;
    try {
      const response = await fetch("/api/dashboard-view-settings", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      dashboardViewSettings = normalizeDashboardViewSettings(result.settings);
      dashboardViewSettingsDefaults = normalizeDashboardViewSettings(result.defaults);
    } catch {
      dashboardViewSettingsError = "表示条件設定の保存に失敗しました";
    } finally {
      savingDashboardViewId = null;
    }
  }

  async function savePastNote() {
    if (isSavingPastNote) return;
    const displayedSymbol = selection.selectedSymbol;
    clearMutationFeedback(noteFeedbackBySymbol, displayedSymbol);
    const symbolValidation = validateNoteDraftForSave();
    if (!symbolValidation.ok) {
      updateMutationFeedback(noteFeedbackBySymbol, displayedSymbol, {
        error: noteDraftSaveError(symbolValidation)
      });
      return;
    }
    const reason = noteReason.trim();
    const note = noteText.trim();
    if (!reason && !note) return;

    const targetSymbol = symbolValidation.symbol;
    const submittedRevision = noteDraftRevision;
    clearMutationFeedback(noteFeedbackBySymbol, targetSymbol);
    isSavingPastNote = true;
    try {
      pastNotes = await savePastNoteRecord({ symbol: targetSymbol, reason, note });
      const completion = completeNoteDraftSave(targetSymbol, submittedRevision);
      updateMutationFeedback(noteFeedbackBySymbol, targetSymbol, {
        notice:
          completion === "newer-draft"
            ? newerDraftSaveNotice
            : "銘柄注記を保存しました"
      });
    } catch {
      updateMutationFeedback(noteFeedbackBySymbol, targetSymbol, {
        error: "銘柄注記の保存に失敗しました"
      });
    } finally {
      isSavingPastNote = false;
    }
  }






  async function reloadSnapshot() {
    await invalidateAll();
    refreshNowMs = Date.now();
    refreshCycleStartedAtMs = refreshNowMs;
  }

  async function refreshServiceSnapshot() {
    if (!snapshot || isAutoReloading) return;
    isAutoReloading = true;
    refreshError = null;
    try {
      serviceState = await fetchCurrentServiceState();
      if (!shouldAutoRefreshDashboard(snapshot, serviceState, pageVisibility)) return;
      const response = await fetch(
        `/api/dashboard/snapshot?afterRunId=${encodeURIComponent(snapshot.runId)}`
      );
      if (response.status === 204) return;
      if (!response.ok) throw new Error(await response.text());
      const candidate: unknown = await response.json();
      if (!isDashboardSnapshot(candidate)) throw new Error("invalid dashboard snapshot response");
      snapshot = candidate;
    } catch (cause) {
      refreshError =
        cause instanceof Error && cause.message
          ? `分析snapshot更新に失敗しました: ${cause.message}`
          : "分析snapshot更新に失敗しました";
    } finally {
      isAutoReloading = false;
      refreshNowMs = Date.now();
      refreshCycleStartedAtMs = refreshNowMs;
    }
  }

  async function fetchCurrentServiceState(): Promise<typeof serviceState> {
    const response = await fetch("/api/service-state", { cache: "no-store" });
    if (response.status === 404) return undefined;
    if (!response.ok) throw new Error(await response.text());
    const candidate: unknown = await response.json();
    if (
      !isRecord(candidate) ||
      !isRecord(candidate.raw) ||
      !isRecord(candidate.view) ||
      !["ok", "stale", "backfilling", "error", "unreadable"].includes(
        String(candidate.view.status)
      )
    ) {
      throw new Error("invalid service state response");
    }
    return candidate as NonNullable<typeof serviceState>;
  }

  async function fetchTickerRuntimeBatch(afterSequence: number) {
    return requestTickerRuntimeBatch(afterSequence, afterSequence > 0);
  }

  async function requestTickerRuntimeBatch(
    afterSequence: number,
    recoverMalformedWithFull: boolean
  ): Promise<TickerRuntimeBatch | undefined> {
    const response = await fetch(`/api/runtime/tickers?after=${afterSequence}`);
    if (response.status === 204) return undefined;
    if (!response.ok) throw new Error(await response.text());

    let candidate: unknown;
    try {
      candidate = await response.json();
    } catch {
      if (recoverMalformedWithFull) return requestTickerRuntimeBatch(0, false);
      throw new Error("invalid ticker runtime response");
    }
    if (isTickerRuntimeBatch(candidate)) return candidate;
    if (recoverMalformedWithFull) return requestTickerRuntimeBatch(0, false);
    throw new Error("invalid ticker runtime response");
  }

  async function refreshLiveSnapshot() {
    isRefreshing = true;
    refreshError = null;
    refreshNotice = null;
    try {
      const response = await fetch("/api/refresh-live", { method: "POST" });
      const result = await parseRefreshLiveResponse(response);
      if (!response.ok) {
        throw new Error(result.message ?? result.error ?? "service snapshot更新に失敗しました");
      }
      await invalidateAll();
      refreshNowMs = Date.now();
      refreshCycleStartedAtMs = refreshNowMs;
      refreshNotice = result.fallback?.message ?? null;
    } catch (cause) {
      refreshError =
        cause instanceof Error && cause.message
          ? `service snapshot更新に失敗しました: ${cause.message}`
          : "service snapshot更新に失敗しました";
    } finally {
      isRefreshing = false;
    }
  }

  async function parseRefreshLiveResponse(response: Response): Promise<RefreshLiveResponse> {
    const contentType = response.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      return (await response.json()) as RefreshLiveResponse;
    }
    return { message: await response.text() };
  }

  function isDashboardSnapshot(value: unknown): value is PrepWatchdeckScannerSnapshot {
    return (
      isRecord(value) &&
      value.schemaVersion === 1 &&
      typeof value.runId === "string" &&
      value.runId.length > 0 &&
      typeof value.generatedAt === "number" &&
      typeof value.dataAsOf === "number" &&
      isRecord(value.summary) &&
      isRecord(value.source) &&
      Array.isArray(value.rows)
    );
  }

  function isTickerRuntimeBatch(value: unknown): value is TickerRuntimeBatch {
    if (
      !isRecord(value) ||
      value.schemaVersion !== 1 ||
      !isPositiveSafeInteger(value.sequence) ||
      !isNonNegativeSafeInteger(value.asOf) ||
      typeof value.full !== "boolean" ||
      !Array.isArray(value.updates)
    ) {
      return false;
    }
    const symbols = new Set<string>();
    return value.updates.every((update) => {
      if (
        !Array.isArray(update) ||
        update.length !== 3 ||
        typeof update[0] !== "string" ||
        !/^[A-Z0-9_-]+$/.test(update[0]) ||
        typeof update[1] !== "number" ||
        !Number.isFinite(update[1]) ||
        update[1] <= 0 ||
        !isPositiveSafeInteger(update[2]) ||
        symbols.has(update[0])
      ) {
        return false;
      }
      symbols.add(update[0]);
      return true;
    });
  }

  function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function isPositiveSafeInteger(value: unknown): value is number {
    return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
  }

  function isNonNegativeSafeInteger(value: unknown): value is number {
    return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
  }

</script>

<svelte:head>
  <title>準備監視板</title>
  <meta
    name="description"
    content="Bitget の検証データ、キャッシュ、ライブスナップショットを確認するローカル向け準備画面。"
  />
</svelte:head>

{#if data.error}
  <main class="error-shell">
    <p>スナップショットエラー</p>
    <h1>データを読み込めませんでした</h1>
    <strong>{data.error}</strong>
  </main>
{:else if snapshot}
  <main class="terminal">
    <DashboardTopbar
      source={snapshot.source}
      status={snapshot.snapshotStatus}
      {serviceState}
      runtime={data.runtime}
      {refreshSecondsRemaining}
      {refreshProgressPct}
      {isAutoReloading}
    />

    <section class="workspace">
      <div class="dashboard-slot candidate-slot" data-dashboard-section="candidate">
        <DashboardRankingArea
          rankings={snapshot?.rankings}
          {selectedTimeframe}
          {candidateRuleText}
          {volumeRatioBaseline}
          {volumeRatioHelp}
          timeframes={rankingTimeframes}
          {metrics}
          onTimeframeSelect={selectRankingTimeframe}
        />
        {#if marketComparisonSummary}
          <DashboardMarketComparisonPanel summary={marketComparisonSummary} />
        {/if}
        {#if vpiSummary}
          <DashboardVpiExperimentPanel
            summary={vpiSummary}
            watchlistCount={rows.length}
            selectableSymbols={visibleRows.map((row) => row.symbol)}
            onSymbolSelect={selectDashboardSymbol}
          />
        {/if}
      </div>

      <div class="dashboard-slot watchlist-slot" data-dashboard-section="watchlist">
        <DashboardWatchQueue
          {rows}
          {visibleRows}
          selectedSymbol={selection.selectedSymbol}
          {selectedTimeframe}
          {rankingTimeframes}
          {rawSortKeys}
          {rawSortDirections}
          {rawSortState}
          {categoryFilters}
          {viewModes}
          {activeCategory}
          {activeView}
          dataAsOf={snapshot.dataAsOf}
          generatedAt={snapshot.generatedAt}
          {pastNotes}
          viewSettings={dashboardViewSettings}
          viewSettingsDefaults={dashboardViewSettingsDefaults}
          viewSettingsError={dashboardViewSettingsError}
          {savingDashboardViewId}
          {isRefreshing}
          {refreshError}
          {refreshNotice}
          {tickerOverlay}
          {tickerStatus}
          {tickerError}
          {volumeRatioBaseline}
          {volumeRatioHelp}
          onCategorySelect={selectCategoryFilter}
          onViewSelect={selectViewMode}
          onSymbolSelect={selectDashboardSymbol}
          onTimeframeSelect={selectRankingTimeframe}
          onRawSortKeyChange={setRawSortKey}
          onRawSortDirectionChange={setRawSortDirection}
          onRawSortQuickSelect={setRawSortQuickSelect}
          onViewSettingsSave={saveDashboardViewSettingsView}
          onViewSettingsReset={resetDashboardViewSettingsView}
          onViewSettingsResetAll={resetAllDashboardViewSettings}
          onReload={reloadSnapshot}
          onRefreshLive={refreshLiveSnapshot}
        />
      </div>

      <aside class="detail" data-dashboard-section="detail" aria-label="選択銘柄の詳細">
        {#if selected}
          {#if conflictingDraftSymbols.length > 0}
            <section class="draft-symbol-warning" role="status">
              <span>保存対象を固定中</span>
              <strong>{conflictingDraftSymbols.map(formatDisplaySymbol).join(" / ")}</strong>
              <p>
                入力中の下書きは上記銘柄に固定されています。対象銘柄へ戻るまで、下書きを上書きする操作は制限されます。
              </p>
            </section>
          {/if}
          {@const range = range24h(selected)}
          <SelectedSymbolOverview
            row={selected}
            {selectedTimeframe}
            {range}
            {volumeRatioBaseline}
            {volumeRatioHelp}
          />
          {#if selectedVpi}
            <SelectedSymbolVpiDetail item={selectedVpi} />
          {/if}
          {#if selectedVenueComparison}
            <SelectedSymbolVenueComparison item={selectedVenueComparison} />
          {/if}
          <SelectedSymbolContext
            row={selected}
            snapshotRunId={snapshot.runId}
            {selectedTimeframe}
            {range}
            {selectedPastNotes}
            {noteReason}
            {noteText}
            {noteSaveError}
            isSaving={isSavingPastNote}
            saveNotice={pastNoteSaveNotice}
            onNoteReasonChange={setNoteReason}
            onNoteTextChange={setNoteText}
            onSavePastNote={savePastNote}
          />
        {:else if selection.selectedSymbol}
          <section class="selection-missing" role="status">
            <span>選択銘柄を保持中</span>
            <h2>{formatDisplaySymbol(selection.selectedSymbol)}</h2>
            <p>
              現在の表示条件またはsnapshotに対象銘柄がありません。別銘柄へ自動切替せず、入力中の下書きも保持しています。
            </p>
            <strong>対象が再表示されるまで保存できません</strong>
          </section>
        {:else}
          <section class="selection-empty" role="status">
            <span>選択対象なし</span>
            <p>現在の表示条件に該当する銘柄がありません。</p>
          </section>
        {/if}
      </aside>

      <div class="dashboard-slot smart-slot" data-dashboard-section="smart-rank">
        <SmartRankControl
          state={smartRankState}
          targetLimit={smartRankTargetLimit}
          maxTargetLimit={SMART_RANK_MAX_TARGET_LIMIT}
          availableRows={visibleRows.length}
          canRun={isSmartRankRunnable}
          cooldownSeconds={smartRankCooldownSeconds}
          onTargetLimitChange={setSmartRankTargetLimit}
          onRun={runSmartRank}
        />
      </div>
    </section>
  </main>
{/if}

<style>
  h1,
  p {
    margin: 0;
  }

  h1 {
    margin-top: var(--space-xxs);
    font-size: clamp(22px, 2.4vw, var(--type-title-lg-size));
    font-weight: var(--type-title-lg-weight);
    line-height: var(--type-title-lg-leading);
    letter-spacing: var(--tracking-default);
  }

  .error-shell {
    display: grid;
    gap: 10px;
    padding: 48px;
  }

  .error-shell strong {
    max-width: 760px;
    color: var(--quality-risk);
    overflow-wrap: anywhere;
    font-size: 13px;
    line-height: 1.45;
  }

  /* Hallmark macrostructure: candidate → watchlist → selected context → corrected ranking.
   * DESIGN.md locked terminal palette; flat surfaces, bounded mobile lists, no information removal.
   */
  .terminal {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    padding: var(--space-page);
    box-sizing: border-box;
    background: var(--bg-alt);
  }

  .workspace {
    order: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      "candidate"
      "watchlist"
      "detail"
      "smart";
    align-items: start;
    gap: var(--space-grid);
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    max-width: 1440px;
    margin: 0 auto 8px;
  }

  .dashboard-slot {
    min-width: 0;
  }

  .candidate-slot {
    grid-area: candidate;
  }

  .watchlist-slot {
    grid-area: watchlist;
  }

  .smart-slot {
    grid-area: smart;
  }

  .detail {
    grid-area: detail;
    min-height: 0;
    position: static;
    max-height: none;
    overflow: visible;
    box-sizing: border-box;
    width: 100%;
    padding-bottom: 0;
    border: 1px solid color-mix(in srgb, var(--muted) 28%, transparent);
    background: var(--panel);
    box-shadow: inset 2px 0 0 color-mix(in srgb, var(--focus) 50%, transparent);
  }

  @media (min-width: 85rem) {
    .workspace {
      grid-template-columns: minmax(0, 1fr) minmax(300px, 330px);
      grid-template-areas:
        "candidate detail"
        "watchlist detail"
        "smart detail";
    }

    .detail {
      position: sticky;
      top: 14px;
      max-height: calc(100vh - 28px);
      overflow: auto;
    }
  }

  .draft-symbol-warning,
  .selection-missing,
  .selection-empty {
    display: grid;
    gap: 8px;
    padding: 14px;
    border-left: 3px solid var(--line-strong);
    background: var(--panel-strong);
  }

  .draft-symbol-warning {
    border-left-color: var(--warning-border);
    border-bottom: 1px solid var(--line-strong);
  }

  .selection-missing {
    border-left-color: var(--quality-risk);
  }

  .draft-symbol-warning span {
    color: var(--warning);
  }

  .selection-missing span {
    color: var(--quality-risk);
  }

  .selection-empty span {
    color: var(--subtle);
  }

  .draft-symbol-warning span,
  .selection-missing span,
  .selection-empty span {
    font-size: 10px;
    font-weight: 800;
    text-transform: uppercase;
  }

  .draft-symbol-warning strong,
  .selection-missing h2 {
    margin: 0;
    color: var(--text);
    font-size: 20px;
    font-weight: 800;
  }

  .draft-symbol-warning p,
  .selection-missing p,
  .selection-empty p {
    color: var(--subtle);
    font-size: 12px;
    line-height: 1.45;
  }

  .selection-missing strong {
    color: var(--quality-risk);
    font-size: 12px;
  }
</style>
