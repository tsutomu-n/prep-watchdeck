<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { page } from "$app/state";
  import { favoriteKey, readUserWorkspace, setFavorite } from "$lib/market/user-workspace";
  import { recordRecentMarket } from "$lib/market/recent-markets";
  import type { UserWorkspace } from "$lib/server/user-workspace-repository";
  import FontSelector from "$lib/components/FontSelector.svelte";
  import ThemeSelector from "$lib/components/ThemeSelector.svelte";
  import DailyReferenceSetting from "$lib/components/DailyReferenceSetting.svelte";
  import MarketPastNotesPanel from "$lib/components/universe/MarketPastNotesPanel.svelte";
  import UniverseChart from "$lib/components/universe/UniverseChart.svelte";
  import SourceQualityInspector from "$lib/components/universe/SourceQualityInspector.svelte";
  import PriceChangeValue from "$lib/components/universe/PriceChangeValue.svelte";
  import { DEFAULT_REFERENCE_TIME } from "$lib/market/price-change";
  import { PriceChangeClient, type PriceChangeState } from "$lib/market/price-change-client";
  import type { Timeframe } from "$lib/market/chart-history";
  import { auditStatusLabel, auditTargetKey } from "$lib/market/candle-audit";
  import type { AuditIndex, AuditIndexEntry } from "$lib/generated/candle-audit-index";
  import type { AuditDetailPage } from "$lib/generated/candle-audit-detail";
  import type { CandleRecoveryState } from "$lib/generated/candle-recovery-state";
  import type { SelectedInstrumentArtifact } from "$lib/generated/selected-market";
  import type { UniverseInstrumentArtifact } from "$lib/generated/universe-snapshot";
  import {
    formatAgeSeconds,
    partitionServiceReasons,
    reasonLabel,
    reasonSummary,
    statusLabel,
    technicalReasonCodes
  } from "$lib/market/market-state-presentation";
  import {
    coverageLabel,
    filterAndSortUniverse,
    formatCompact,
    formatFinite,
    formatPrice,
    formatBidAsk,
    spreadBps,
    sortNativeRows,
    type NativeSort,
    formatRate,
    formatTimestamp,
    groupVenueCounts,
    type CoverageFilter,
    type QualityFilter,
    type VenueFilter
  } from "$lib/market/universe-view";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import type { MarketMetricsArtifact, MarketMetricRow, MetricValue } from "$lib/generated/market-metrics";

  const artifactPollMs = 5_000;
  const heartbeatMs = 5 * 60 * 1_000;

  let { data }: { data: { market?: MarketArtifactBundle; marketError?: string } } = $props();
  const initialMarket = untrack(() =>
    "market" in data ? (data.market as MarketArtifactBundle) : null
  );
  const initialError = untrack(() =>
    "marketError" in data ? String(data.marketError) : null
  );
  let market = $state<MarketArtifactBundle | null>(initialMarket);
  let marketError = $state<string | null>(initialError);
  let metrics = $state<MarketMetricsArtifact | null>(null);
  let metricsError = $state<string | null>(null);
  let metricsRequestId = 0;
  let refreshError = $state<string | null>(null);
  let refreshing = false;
  let search = $state("");
  let venue = $state<VenueFilter>("all");
  let coverage = $state<CoverageFilter>("all");
  let quality = $state<QualityFilter>("all");
  let nativeSort = $state<NativeSort>("base");
  let nativeDirection = $state<"asc" | "desc">("desc");
  let minTrade15m = $state<number | null>(null);
  let lockedIds = $state<string[] | null>(null);
  let favoritesOnly = $state(false);
  let workspace = $state<UserWorkspace | null>(null);
  let workspaceError = $state<string | null>(null);
  let favoriteBusy = $state<Set<string>>(new Set());
  let favoriteIntent = $state<Record<string, boolean>>({});
  let viewName = $state("");
  let selectedViewId = $state("");
  let viewBusy = $state(false);
  let selectedVenueInstrumentId = $state<string | null>(initialSelection(initialMarket));
  let selectionMessage = $state<string | null>(null);
  let selectionError = $state<string | null>(null);
  let selectionToken = $state<string | null>(null);
  let selectionQueue: Promise<void> = Promise.resolve();
  let wantedSelectionKey = "";
  let chartTimeframe = $state<Timeframe>("15m");
  let referenceTime = $state(DEFAULT_REFERENCE_TIME);
  let referenceReady = $state(false);
  let priceNow = $state(Date.now());
  let priceChanges = $state<Record<string, PriceChangeState>>({});
  let visiblePriceIds = $state<Set<string>>(new Set());
  let priceChangeClient = $state<PriceChangeClient | null>(null);
  let priceObserver: IntersectionObserver | null = null;
  const observedPriceRows = new Map<Element, string>();
  let auditIndex = $state<AuditIndex | null>(null);
  let auditIndexStatus = $state<"loading" | "available" | "not_run" | "unavailable">("loading");
  let recovery = $state<CandleRecoveryState | null>(null);
  let recoveryStatus = $state<"loading" | "available" | "not_run" | "unavailable">("loading");
  let qualityFetchedAt = $state<string | null>(null);
  let qualityRefreshBusy = false;
  let sourceQualityOpen = $state(false);
  let pinnedAuditRunId = $state<string | null>(null);
  let auditDetail = $state<AuditDetailPage | null>(null);
  let auditDetailError = $state<string | null>(null);
  let auditDetailLoading = $state(false);
  let auditOffset = $state(0);
  let auditMarkersEnabled = $state(false);
  let auditJump = $state<{ bucketAt: string; sequence: number } | null>(null);
  let auditJumpMessage = $state<string | null>(null);
  let auditDetailController: AbortController | null = null;
  let auditDetailRequestId = 0;
  let auditSelectionGeneration = 0;
  let auditLastSelectionKey = "";

  let items = $derived((market?.universe.items ?? []).map(item => {
    const observed = item.observedAt ? Date.parse(item.observedAt) : NaN;
    const source = item.sourceAt ? Date.parse(item.sourceAt) : observed;
    if ((item.quality === "ready" || item.quality === "partial") &&
        (!Number.isFinite(observed) || !Number.isFinite(source) ||
          observed > priceNow || source > priceNow ||
          priceNow - observed > 120_000 || priceNow - source > 120_000)) {
      return { ...item, quality: "stale" as const };
    }
    return item;
  }));
  let groupCounts = $derived(groupVenueCounts(items));
  let filteredItems = $derived(filterAndSortUniverse(items, { search, venue, coverage, quality })
    .filter((item) => minTrade15m === null ||
      (metricCurrent(metricFor(item)?.tradeChange["15m"], 300) ?? -Infinity) >= minTrade15m)
    .filter((item) => !favoritesOnly || Boolean(workspace?.favorites.some((entry) =>
      entry.kind === "instrument" && entry.id === item.venueInstrumentId &&
      entry.version === item.venueInstrumentVersionId))));
  let sortedItems = $derived(sortNativeRows(filteredItems, nativeSort, nativeDirection, metricFor, priceNow));
  let visibleItems = $derived(lockedIds ? lockedIds.flatMap((id) => {
    const item = sortedItems.find((row) => row.venueInstrumentId === id);
    return item ? [item] : [];
  }) : sortedItems);
  let selectedInstrument = $derived(
    items.find((item) => item.venueInstrumentId === selectedVenueInstrumentId) ?? null
  );
  let auditEntryMap = $derived(new Map((auditIndex?.entries ?? []).map((entry) => [
    auditTargetKey(entry.target.venueInstrumentId, entry.target.venueInstrumentVersionId), entry
  ])));
  let selectedAuditEntry = $derived(selectedInstrument ?
    auditEntryMap.get(auditTargetKey(selectedInstrument.venueInstrumentId,
      selectedInstrument.venueInstrumentVersionId)) ?? null : null);
  let selectedAuditKey = $derived(selectedInstrument ?
    auditTargetKey(selectedInstrument.venueInstrumentId, selectedInstrument.venueInstrumentVersionId) : "");
  let auditIdentityValid = $derived(Boolean(auditDetail && selectedInstrument &&
    auditDetail.report.target.venueInstrumentId === selectedInstrument.venueInstrumentId &&
    auditDetail.report.target.venueInstrumentVersionId === selectedInstrument.venueInstrumentVersionId &&
    auditDetail.report.series?.venue === selectedInstrument.venue &&
    auditDetail.report.series?.sourceSymbol === selectedInstrument.sourceSymbol &&
    auditDetail.report.series?.baseAsset === selectedInstrument.baseAsset &&
    auditDetail.report.series?.quoteAsset === selectedInstrument.quoteAsset &&
    auditDetail.report.series?.settleAsset === selectedInstrument.settleAsset));
  let selectedMetrics = $derived(selectedInstrument ? metricFor(selectedInstrument) : null);

  function metricFor(item: UniverseInstrumentArtifact): MarketMetricRow | null {
    if (!metrics || Math.abs(priceNow - Date.parse(metrics.generatedAt)) > 120_000) return null;
    return metrics?.rows.find((row) => row.venueInstrumentId === item.venueInstrumentId &&
      row.venueInstrumentVersionId === item.venueInstrumentVersionId) ?? null;
  }

  function metricCurrent(value: MetricValue | undefined, maxAgeSeconds: number): number | null {
    const end = value?.endAt ? Date.parse(value.endAt) : Number.NaN;
    const source = value?.endSourceAt ? Date.parse(value.endSourceAt) : end;
    return value?.availability === "available" && value.value !== null &&
      Number.isFinite(end) && Number.isFinite(source) &&
      end <= priceNow && source <= priceNow &&
      priceNow - end <= maxAgeSeconds * 1000 &&
      priceNow - source <= maxAgeSeconds * 1000 ? value.value : null;
  }

  function metricLabel(value: MetricValue | undefined, maxAgeSeconds = 300): string {
    const current = metricCurrent(value, maxAgeSeconds);
    return current === null ? "—" : `${current > 0 ? "+" : ""}${current.toFixed(2)}%`;
  }
  let selectedGroupId = $derived(selectedInstrument?.groupId ?? null);
  let selectedVersionId = $derived(selectedInstrument?.venueInstrumentVersionId);
  let selectedPayload = $derived(
    market?.selected.selection?.groupId === selectedGroupId &&
      market.selected.selection.primaryVenueInstrumentId === selectedVenueInstrumentId &&
      market.selected.selection.instruments.some((instrument) =>
        instrument.venueInstrumentId === selectedVenueInstrumentId &&
        instrument.venueInstrumentVersionId === selectedInstrument?.venueInstrumentVersionId)
      ? market.selected.selection
      : null
  );
  let groupVenueCount = $derived(
    selectedGroupId ? (groupCounts.get(selectedGroupId) ?? 1) : 1
  );
  let snapshotFrozen = $derived(Boolean(market && refreshError));
  let lastVerifiedAt = $derived(market?.service.generatedAt ?? market?.universe.generatedAt ?? null);
  let serviceReasons = $derived(partitionServiceReasons(market?.service.qualityReasons ?? []));
  let operationalReasons = $derived(serviceReasons.operational);
  let globalReasons = $derived([
    ...serviceReasons.quality,
    ...(market?.universe.qualityReasons ?? [])
  ]);

  onMount(() => {
    const loadWorkspace = () => {
      if (document.visibilityState !== "hidden") {
        void readUserWorkspace().then((value) => { workspace = value; workspaceError = null; })
          .catch(() => workspaceError = "お気に入りを読み込めません");
      }
    };
    loadWorkspace();
    document.addEventListener("visibilitychange", loadWorkspace);
    const requestedId = page.url.searchParams.get("instrument");
    const requestedVersion = Number(page.url.searchParams.get("version"));
    const target = market?.universe.items.find((item) => item.active &&
      item.venueInstrumentId === requestedId &&
      item.venueInstrumentVersionId === requestedVersion);
    if (target) selectedVenueInstrumentId = target.venueInstrumentId;
    const timer = window.setInterval(() => {
      void refreshArtifacts();
      void refreshMetrics();
    }, artifactPollMs);
    void refreshMetrics();
    const client = new PriceChangeClient({
      onUpdate: (id, state) => { priceChanges[id] = state; }
    });
    priceChangeClient = client;
    function refreshPriceChanges() {
      priceNow = Date.now();
      client.refresh();
    }
    const priceTimer = window.setInterval(refreshPriceChanges, 15_000);
    let boundaryTimer: ReturnType<typeof setTimeout>;
    function watchMinuteBoundary() {
      boundaryTimer = setTimeout(() => {
        refreshPriceChanges();
        watchMinuteBoundary();
      }, 60_000 - (Date.now() % 60_000) + 10);
    }
    watchMinuteBoundary();
    function syncVisibility() {
      priceNow = Date.now();
      client.setPaused(document.visibilityState === "hidden");
    }
    document.addEventListener("visibilitychange", syncVisibility);
    syncVisibility();
    void refreshQuality();
    const qualityTimer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void refreshQuality();
    }, 60_000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(priceTimer);
      window.clearInterval(qualityTimer);
      window.clearTimeout(boundaryTimer);
      document.removeEventListener("visibilitychange", syncVisibility);
      document.removeEventListener("visibilitychange", loadWorkspace);
      priceObserver?.disconnect();
      client.dispose();
      priceChangeClient = null;
      auditDetailController?.abort();
    };
  });

  $effect(() => {
    const key = selectedAuditKey;
    if (key === auditLastSelectionKey) return;
    auditLastSelectionKey = key;
    auditSelectionGeneration++;
    auditDetailRequestId++;
    auditDetailController?.abort();
    auditDetailController = null;
    pinnedAuditRunId = null;
    auditDetail = null;
    auditDetailError = null;
    auditDetailLoading = false;
    auditOffset = 0;
    auditMarkersEnabled = false;
    auditJump = null;
    auditJumpMessage = null;
    sourceQualityOpen = false;
  });

  async function refreshQuality() {
    if (qualityRefreshBusy || document.visibilityState === "hidden") return;
    qualityRefreshBusy = true;
    try {
      const [indexResult, recoveryResult] = await Promise.allSettled([
        fetch("/api/candle-audits", { cache: "no-store" }),
        fetch("/api/candle-recovery", { cache: "no-store" })
      ]);
      if (indexResult.status === "fulfilled") {
        try {
          const response = indexResult.value;
          if (!response.ok) throw new Error("audit index unavailable");
          const value = await response.json() as { state: "available" | "not_run"; index: AuditIndex | null };
          if (value.state === "available" && value.index) {
            auditIndex = value.index;
            auditIndexStatus = "available";
          } else if (value.state === "not_run") {
            auditIndex = null;
            auditIndexStatus = "not_run";
          } else throw new Error("audit index invalid");
        } catch { auditIndexStatus = "unavailable"; }
      } else auditIndexStatus = "unavailable";
      if (recoveryResult.status === "fulfilled") {
        try {
          const response = recoveryResult.value;
          if (!response.ok) throw new Error("recovery unavailable");
          const value = await response.json() as { state: "available" | "not_run"; recovery: CandleRecoveryState | null };
          if (value.state === "available" && value.recovery) {
            recovery = value.recovery;
            recoveryStatus = "available";
          } else if (value.state === "not_run") {
            recovery = null;
            recoveryStatus = "not_run";
          } else throw new Error("recovery state invalid");
        } catch { recoveryStatus = "unavailable"; }
      } else recoveryStatus = "unavailable";
      qualityFetchedAt = new Date().toISOString();
    } finally { qualityRefreshBusy = false; }
  }

  async function loadAuditDetail(runId: string, offset = 0) {
    const generation = auditSelectionGeneration;
    const key = selectedAuditKey;
    const requestId = ++auditDetailRequestId;
    auditDetailController?.abort();
    const controller = new AbortController();
    auditDetailController = controller;
    auditDetailLoading = true;
    auditDetailError = null;
    try {
      const response = await fetch(`/api/candle-audits/${runId}?offset=${offset}&limit=200`, {
        cache: "no-store", signal: controller.signal
      });
      if (!response.ok) throw new Error(response.status === 404 ? "照合記録が見つかりません" : "照合記録を取得できません");
      const value = await response.json() as AuditDetailPage;
      if (generation !== auditSelectionGeneration || requestId !== auditDetailRequestId ||
          key !== selectedAuditKey || pinnedAuditRunId !== runId || value.report.runId !== runId ||
          value.offset !== offset || value.report.target.venueInstrumentId !== selectedInstrument?.venueInstrumentId ||
          value.report.target.venueInstrumentVersionId !== selectedInstrument?.venueInstrumentVersionId) return;
      auditDetail = value;
      auditOffset = offset;
      auditDetailError = null;
    } catch {
      if (generation === auditSelectionGeneration && requestId === auditDetailRequestId &&
          key === selectedAuditKey && !controller.signal.aborted) {
        auditDetailError = "照合記録の更新取得に失敗しました";
      }
    } finally {
      if (generation === auditSelectionGeneration && requestId === auditDetailRequestId) {
        auditDetailLoading = false;
      }
    }
  }

  function selectAuditRun(runId: string) {
    pinnedAuditRunId = runId;
    auditDetail = null;
    auditMarkersEnabled = false;
    auditOffset = 0;
    void loadAuditDetail(runId);
  }

  function setSourceQualityOpen(open: boolean) {
    sourceQualityOpen = open;
    if (open && !pinnedAuditRunId && selectedAuditEntry) selectAuditRun(selectedAuditEntry.runId);
  }

  async function openAuditFor(instrument: UniverseInstrumentArtifact) {
    selectInstrument(instrument);
    await tick();
    sourceQualityOpen = true;
    const entry = auditEntryMap.get(auditTargetKey(instrument.venueInstrumentId,
      instrument.venueInstrumentVersionId));
    if (entry) selectAuditRun(entry.runId);
    await tick();
    document.getElementById("source-quality-heading")?.focus();
  }

  function showAuditFinding(offset: number) {
    if (!pinnedAuditRunId) return;
    sourceQualityOpen = true;
    void loadAuditDetail(pinnedAuditRunId, Math.floor(offset / 200) * 200).then(async () => {
      await tick();
      document.getElementById(`audit-finding-${offset}`)?.focus();
    });
  }

  $effect(() => {
    const client = priceChangeClient;
    if (!client || !referenceReady) return;
    const time = referenceTime;
    const wanted = new Set([selectedVenueInstrumentId, ...visiblePriceIds]);
    const ordered = [selectedInstrument, ...items.filter((item) => visiblePriceIds.has(item.venueInstrumentId))];
    const targets = ordered.filter((item): item is UniverseInstrumentArtifact => Boolean(
      item?.active && wanted.has(item.venueInstrumentId)
    ));
    untrack(() => {
      client.setReferenceTime(time);
      client.setTargets(targets);
    });
  });

  function observePriceRow(node: HTMLElement, id: string) {
    if (!priceObserver) {
      priceObserver = new IntersectionObserver((entries) => {
        const next = new Set(visiblePriceIds);
        for (const entry of entries) {
          const rowId = observedPriceRows.get(entry.target);
          if (!rowId) continue;
          if (entry.isIntersecting) next.add(rowId);
          else next.delete(rowId);
        }
        visiblePriceIds = next;
      });
    }
    observedPriceRows.set(node, id);
    priceObserver.observe(node);
    return {
      destroy() {
        priceObserver?.unobserve(node);
        observedPriceRows.delete(node);
        const next = new Set(visiblePriceIds);
        next.delete(id);
        visiblePriceIds = next;
      }
    };
  }

  $effect(() => {
    if (selectedVenueInstrumentId && selectedInstrument) return;
    selectedVenueInstrumentId = visibleItems[0]?.venueInstrumentId ?? items[0]?.venueInstrumentId ?? null;
  });

  $effect(() => {
    const groupId = selectedGroupId;
    const venueInstrumentId = selectedVenueInstrumentId;
    const versionId = selectedVersionId;
    const token = selectionToken;
    if (!groupId || !venueInstrumentId || !versionId || !token) return;
    const heartbeat = window.setInterval(() => {
      if (document.visibilityState !== "hidden") {
        selectionQueue = selectionQueue.catch(() => undefined).then(
          () => postSelection("heartbeat", groupId, venueInstrumentId, versionId, token)
        );
      }
    }, heartbeatMs);
    return () => window.clearInterval(heartbeat);
  });

  async function refreshArtifacts() {
    if (refreshing || document.visibilityState === "hidden") return;
    refreshing = true;
    try {
      const response = await fetch("/api/market-data", { cache: "no-store" });
      if (!response.ok) throw new Error("market artifacts unavailable");
      market = (await response.json()) as MarketArtifactBundle;
      marketError = null;
      refreshError = null;
    } catch (cause) {
      refreshError = cause instanceof Error ? cause.message : "latest market unavailable";
    } finally {
      refreshing = false;
    }
  }

  async function refreshMetrics() {
    if (document.visibilityState === "hidden") return;
    const current = ++metricsRequestId;
    try {
      const response = await fetch("/api/market-metrics", { cache: "no-store" });
      if (!response.ok) throw new Error("metrics unavailable");
      const next = await response.json() as MarketMetricsArtifact;
      if (current !== metricsRequestId ||
          (metrics && (Date.parse(next.candleCutoff) < Date.parse(metrics.candleCutoff) ||
            (next.candleCutoff === metrics.candleCutoff &&
              Date.parse(next.generatedAt) < Date.parse(metrics.generatedAt))))) return;
      metrics = next;
      metricsError = null;
    } catch {
      if (current === metricsRequestId) metricsError = "追加指標を取得できません";
    }
  }

  async function postSelection(
    action: "select" | "heartbeat", groupId: string, venueInstrumentId: string,
    versionId: number, expectedRequestedAt?: string
  ) {
    const key = `${venueInstrumentId}/${versionId}`;
    if (action === "select" && wantedSelectionKey !== key) return;
    if (action === "heartbeat" && (selectedVenueInstrumentId !== venueInstrumentId ||
        selectedInstrument?.venueInstrumentVersionId !== versionId ||
        selectionToken !== expectedRequestedAt || document.visibilityState === "hidden")) return;
    try {
      const response = await fetch("/api/selection", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action, groupId, venueInstrumentId, venueInstrumentVersionId: versionId,
          ...(action === "heartbeat" ? { expectedRequestedAt } : {})
        })
      });
      if (!response.ok) throw new Error("selection request failed");
      const result = await response.json() as { command: { requestedAt: string } };
      if (selectedVenueInstrumentId === venueInstrumentId &&
          selectedInstrument?.venueInstrumentVersionId === versionId) {
        selectionToken = result.command.requestedAt;
        selectionError = null;
        selectionMessage = action === "heartbeat" ? "選択監視を継続しました" : "詳細データを要求しました";
      }
    } catch {
      if (selectedVenueInstrumentId === venueInstrumentId &&
          selectedInstrument?.venueInstrumentVersionId === versionId) {
        selectionToken = null;
        selectionError = "選択監視を更新できません。市場データ品質とは別の操作エラーです。";
      }
    }
  }

  function selectInstrument(instrument: UniverseInstrumentArtifact) {
    selectedVenueInstrumentId = instrument.venueInstrumentId;
    try {
      recordRecentMarket(window.localStorage, {
        key: `instrument:${instrument.venueInstrumentId}:${instrument.venueInstrumentVersionId}`,
        label: `${instrument.baseAsset} · ${instrument.venue}`,
        href: `/?mode=native&instrument=${encodeURIComponent(instrument.venueInstrumentId)}&version=${instrument.venueInstrumentVersionId}`
      });
    } catch { /* The current selection remains usable without browser storage. */ }
    selectionToken = null;
    selectionMessage = null;
    selectionError = null;
    wantedSelectionKey = `${instrument.venueInstrumentId}/${instrument.venueInstrumentVersionId}`;
    if (instrument.active && instrument.groupId) {
      const { groupId, venueInstrumentId, venueInstrumentVersionId } = instrument;
      selectionQueue = selectionQueue.catch(() => undefined).then(() =>
        postSelection("select", groupId, venueInstrumentId, venueInstrumentVersionId)
      );
    }
  }

  async function toggleFavorite(instrument: UniverseInstrumentArtifact) {
    const target = {
      kind: "instrument" as const,
      id: instrument.venueInstrumentId,
      version: instrument.venueInstrumentVersionId
    };
    const key = favoriteKey(target);
    const current = favoriteIntent[key] ?? Boolean(workspace?.favorites.some((entry) => favoriteKey(entry) === key));
    favoriteIntent = { ...favoriteIntent, [key]: !current };
    if (favoriteBusy.has(key)) return;
    favoriteBusy = new Set([...favoriteBusy, key]);
    try {
      while (true) {
        const desired = favoriteIntent[key];
        workspace = await setFavorite(target, desired);
        workspaceError = null;
        if (favoriteIntent[key] === desired) break;
      }
    } catch (cause) {
      workspaceError = cause instanceof Error ? cause.message : "お気に入りを保存できません";
      try { workspace = await readUserWorkspace(); } catch { /* Keep the explicit error visible. */ }
    } finally {
      const nextIntent = { ...favoriteIntent }; delete nextIntent[key]; favoriteIntent = nextIntent;
      const next = new Set(favoriteBusy); next.delete(key); favoriteBusy = next;
    }
  }

  async function mutateView(action: "saveView" | "removeView") {
    if (!workspace || viewBusy || (action === "saveView" && !viewName.trim()) ||
        (action === "removeView" && !selectedViewId)) return;
    viewBusy = true;
    try {
      const response = await fetch("/api/user-workspace", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify(action === "saveView" ? {
          action, id: selectedViewId || crypto.randomUUID(), name: viewName.trim(),
          expectedRevision: workspace.revision,
          view: { mode: "native", search, venue, coverage, quality, favoritesOnly,
            nativeSort, nativeDirection, minTrade15m }
        } : { action, id: selectedViewId, expectedRevision: workspace.revision })
      });
      if (!response.ok) throw new Error(response.status === 409
        ? "別の画面で表示設定が更新されました。再読込してください。" : "表示設定を保存できません");
      workspace = await response.json() as UserWorkspace;
      if (action === "removeView") { selectedViewId = ""; viewName = ""; }
      workspaceError = null;
    } catch (cause) {
      workspaceError = cause instanceof Error ? cause.message : "表示設定を保存できません";
    } finally { viewBusy = false; }
  }

  function applySavedView(id: string) {
    selectedViewId = id;
    const saved = workspace?.savedViews.find((item) => item.id === id);
    if (!saved || saved.view.mode !== "native") return;
    const view = saved.view;
    search = typeof view.search === "string" ? view.search : "";
    venue = ["all", "bitget", "hyperliquid", "aster"].includes(String(view.venue))
      ? view.venue as VenueFilter : "all";
    coverage = ["all", "multi", "single"].includes(String(view.coverage))
      ? view.coverage as CoverageFilter : "all";
    quality = ["all", "ready", "partial", "stale", "unavailable"].includes(String(view.quality))
      ? view.quality as QualityFilter : "all";
    favoritesOnly = view.favoritesOnly === true;
    nativeSort = ["base", "funding", "spread", "oi15m", "oi1h", "trade15m", "trade1h", "trade24h"]
      .includes(String(view.nativeSort)) ? view.nativeSort as NativeSort : "base";
    nativeDirection = view.nativeDirection === "asc" ? "asc" : "desc";
    minTrade15m = typeof view.minTrade15m === "number" ? view.minTrade15m : null;
    lockedIds = null;
    viewName = saved.name;
  }

  function returnHref() {
    const params = page.url.searchParams;
    const query = new URLSearchParams({
      period: params.get("returnPeriod") ?? "24h",
      order: params.get("returnOrder") ?? "turnover",
      dailyReferenceJst: params.get("returnReference") ?? "00:00",
      minTurnover: params.get("returnMinimum") ?? "0",
      selected: params.get("returnSelected") ?? "",
      q: params.get("returnSearch") ?? "",
      venue: params.get("returnVenue") ?? "all",
      includeUnranked: params.get("returnIncludeUnranked") ?? "0",
      favoritesOnly: params.get("returnFavoritesOnly") ?? "0",
      sort: params.get("returnSort") ?? "server",
      direction: params.get("returnDirection") ?? "asc",
      ratioPeriod: params.get("returnRatioPeriod") ?? "15m",
      minRatio: params.get("returnMinRatio") ?? "",
      minDayPosition: params.get("returnMinDayPosition") ?? "",
      maxDayPosition: params.get("returnMaxDayPosition") ?? "",
      preset: params.get("returnPreset") ?? "standard",
      listTop: params.get("returnListTop") ?? "0",
      listLeft: params.get("returnListLeft") ?? "0",
      restoreList: params.get("returnRestoreList") ?? "0"
    });
    return `/rankings?${query}`;
  }

  function depthRows(instrument: SelectedInstrumentArtifact) {
    return Array.from(
      { length: Math.max(instrument.bids.length, instrument.asks.length) },
      (_, index) => ({ bid: instrument.bids[index], ask: instrument.asks[index] })
    );
  }

  function initialSelection(bundle: MarketArtifactBundle | null) {
    if (!bundle) return null;
    const active = new Set(
      bundle.universe.items.filter((item) => item.active).map((item) => item.venueInstrumentId)
    );
    const current = bundle.selected.selection?.primaryVenueInstrumentId;
    if (current && active.has(current)) return current;
    return filterAndSortUniverse(bundle.universe.items, {
      search: "",
      venue: "all",
      coverage: "all",
      quality: "all"
    })[0]?.venueInstrumentId ?? null;
  }
</script>

<svelte:head>
  <title>Perp Universe Explorer | Prep Watchdeck</title>
  <meta
    name="description"
    content="Bitget、Hyperliquid、Asterの暗号資産Perpを会場別に確認するローカル監視画面"
  />
</svelte:head>

<main class="universe-page">
  <header class="topbar">
    <div class="identity">
      <p>PREP WATCHDECK</p>
      <h1>Perp Universe Explorer</h1>
      <span>Bitget / Hyperliquid / Aster の公開データ監視。売買推奨ではありません。</span>
    </div>
    <div class="preferences" aria-label="表示設定">
      <a class="ranking-link" href={returnHref()}>参照市場へ戻る</a>
      <ThemeSelector />
      <FontSelector />
      <DailyReferenceSetting bind:value={referenceTime} bind:ready={referenceReady} />
    </div>
  </header>

  {#if marketError && !market}
    <section class="fatal-state" aria-labelledby="fatal-title">
      <h2 id="fatal-title">市場artifactを表示できません</h2>
      <p role="alert">検証済みの市場snapshotがありません。</p>
      <button type="button" onclick={() => window.location.reload()}>再読込</button>
    </section>
  {:else if market}
    <section class="status-strip" aria-label="データ状態">
      <div>
        <span>全体</span>
        <strong class:quality-risk={market.service.status !== "ready"}>
          {statusLabel(market.service.status)}
        </strong>
      </div>
      <div>
        <span>Catalog</span>
        <strong class:quality-risk={market.service.catalog.status !== "ready"}>
          {statusLabel(market.service.catalog.status)} · {formatAgeSeconds(market.service.catalog.ageSeconds)}
        </strong>
      </div>
      <div>
        <span>L1</span>
        <strong class:quality-risk={market.service.l1.status !== "ready"}>
          {statusLabel(market.service.l1.status)} · {formatAgeSeconds(market.service.l1.ageSeconds)}
        </strong>
      </div>
      <div>
        <span>Universe</span>
        <strong>{items.length} instruments</strong>
      </div>
      <div>
        <span>表示データ生成</span>
        <strong>{formatTimestamp(lastVerifiedAt)}</strong>
        <span>JST</span>
      </div>
    </section>

    {#if snapshotFrozen}
      <section class="operational-banner" role="status" aria-live="polite">
        <strong>更新停止</strong>
        <span>
          最新データを取得できません。以下は{formatTimestamp(lastVerifiedAt)}に最後に検証できたsnapshotです。
        </span>
      </section>
    {/if}

    {#if operationalReasons.length > 0}
      <section class="operational-banner" aria-label="運用上の注意">
        <strong>運用上の注意</strong>
        <span>{reasonSummary(operationalReasons)}</span>
        <details>
          <summary>技術情報</summary>
          <code>{technicalReasonCodes(operationalReasons).join(" / ")}</code>
        </details>
      </section>
    {/if}

    {#if globalReasons.length > 0}
      <section class="quality-banner" aria-label="データ品質理由">
        <strong>品質理由</strong>
        <span>{reasonSummary(globalReasons)}</span>
        <details>
          <summary>技術情報</summary>
          <code>{technicalReasonCodes(globalReasons).join(" / ")}</code>
        </details>
      </section>
    {/if}

    <div class="workspace">
      <section class="universe" aria-labelledby="universe-title">
        <div class="section-title">
          <div>
            <h2 id="universe-title">Instrument Universe</h2>
            <p>既定順: base asset → Venue。約定騰落率はJST {referenceTime}基準。</p>
          </div>
          <strong>{visibleItems.length} / {items.length}</strong>
        </div>

        <div class="filters" aria-label="Universe絞り込み">
          <label><span>保存</span><span><input type="checkbox" bind:checked={favoritesOnly} />お気に入りのみ</span></label>
          <label class="search-control">
            <span>検索</span>
            <input bind:value={search} type="search" placeholder="BTC / BTCUSDT / venue id" />
          </label>
          <label>
            <span>Venue</span>
            <select bind:value={venue}>
              <option value="all">すべて</option>
              <option value="aster">Aster</option>
              <option value="bitget">Bitget</option>
              <option value="hyperliquid">Hyperliquid</option>
            </select>
          </label>
          <label>
            <span>Coverage</span>
            <select bind:value={coverage}>
              <option value="all">すべて</option>
              <option value="multi">2 Venue以上</option>
              <option value="single">単独 / 未group</option>
            </select>
          </label>
          <label>
            <span>品質</span>
            <select bind:value={quality}>
              <option value="all">すべて</option>
              <option value="ready">正常</option>
              <option value="partial">一部取得</option>
              <option value="stale">期限切れ</option>
              <option value="unavailable">取得不能</option>
            </select>
          </label>
          <label><span>並べ替え</span><select aria-label="取引所別の並べ替え" bind:value={nativeSort}>
            <option value="base">銘柄順</option><option value="funding">Funding/h</option>
            <option value="spread">Spread bps</option><option value="oi15m">数量OI 15分</option>
            <option value="oi1h">数量OI 1時間</option><option value="trade15m">確定終値 15分</option>
            <option value="trade1h">確定終値 1時間</option><option value="trade24h">確定終値 24時間</option>
          </select></label>
          <label><span>方向</span><select aria-label="並べ替え方向" bind:value={nativeDirection}>
            <option value="desc">大きい順</option><option value="asc">小さい順</option>
          </select></label>
          <label><span>確定終値15分の下限</span><input type="number" step="any" value={minTrade15m ?? ""}
            oninput={(event) => minTrade15m = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        </div>
        <button type="button" onclick={() => lockedIds = lockedIds ? null : visibleItems.map((item) => item.venueInstrumentId)}>
          {lockedIds ? "行順固定を解除" : "行順を固定"}
        </button>
        {#if workspaceError}<p class="quality-banner" role="alert">{workspaceError}</p>{/if}
        <div class="filters" aria-label="表示条件の保存">
          <label><span>保存した表示</span><select aria-label="取引所別の保存した表示" value={selectedViewId}
            onchange={(event) => applySavedView(event.currentTarget.value)}>
            <option value="">選択してください</option>
            {#each workspace?.savedViews.filter((item) => item.view.mode === "native") ?? [] as saved}
              <option value={saved.id}>{saved.name}</option>
            {/each}
          </select></label>
          <label><span>表示名</span><input aria-label="取引所別の表示名" maxlength="80" bind:value={viewName} /></label>
          <button type="button" disabled={viewBusy || !workspace || !viewName.trim()} onclick={() => mutateView("saveView")}>表示条件を保存</button>
          <button type="button" disabled={viewBusy || !selectedViewId} onclick={() => mutateView("removeView")}>保存した表示を削除</button>
        </div>

        <div class="table-scroll">
          <table>
            <caption class="sr-only">Perp instrument一覧</caption>
            <thead>
              <tr>
                <th scope="col">保存</th>
                <th scope="col">Instrument</th>
                <th scope="col">Mark</th>
                <th scope="col" class="change-column">約定騰落率<small>JST {referenceTime}基準</small></th>
                <th scope="col">Bid / Ask</th>
                <th scope="col">Funding / h</th>
                <th scope="col" class="optional-column">OI notional</th>
                <th scope="col" class="optional-column">数量OI 15m / 1h</th>
                <th scope="col" class="optional-column">確定終値 15m / 1h / 24h</th>
                <th scope="col" class="optional-column">24h volume</th>
                <th scope="col">品質 / age</th>
              </tr>
            </thead>
            <tbody>
              {#each visibleItems as item (item.venueInstrumentId)}
                <tr
                  class:selected={item.venueInstrumentId === selectedVenueInstrumentId}
                  use:observePriceRow={item.venueInstrumentId}
                >
                  <td><button type="button"
                    aria-label={`${item.baseAsset} ${item.venue}をお気に入り${(favoriteIntent[`instrument:${item.venueInstrumentId}:${item.venueInstrumentVersionId}`] ?? workspace?.favorites.some((entry) => entry.kind === "instrument" && entry.id === item.venueInstrumentId && entry.version === item.venueInstrumentVersionId)) ? "解除" : "登録"}`}
                    aria-pressed={favoriteIntent[`instrument:${item.venueInstrumentId}:${item.venueInstrumentVersionId}`] ?? workspace?.favorites.some((entry) => entry.kind === "instrument" && entry.id === item.venueInstrumentId && entry.version === item.venueInstrumentVersionId) ?? false}
                    onclick={() => toggleFavorite(item)}>★</button></td>
                  <td>
                    <button
                      type="button"
                      class="instrument-select"
                      aria-current={item.venueInstrumentId === selectedVenueInstrumentId ? "true" : undefined}
                      aria-label={`${item.baseAsset} ${item.venue}を詳細表示`}
                      onclick={() => selectInstrument(item)}
                    >
                      <strong>{item.baseAsset}</strong>
                      <span>{item.venue} · {item.sourceSymbol}</span>
                      <small class="coverage-label">{coverageLabel(item, groupCounts)}</small>
                    </button>
                  </td>
                  <td class="numeric">
                    {formatPrice(item.markPrice)}
                    <div class="mobile-change">
                      <small>約定騰落率</small>
                      <PriceChangeValue
                        state={priceChanges[item.venueInstrumentId]}
                        {referenceTime}
                        versionId={item.venueInstrumentVersionId}
                        now={priceNow}
                        supported={item.active}
                      />
                    </div>
                  </td>
                  <td class="numeric change-column">
                    <PriceChangeValue
                      state={priceChanges[item.venueInstrumentId]}
                      {referenceTime}
                      versionId={item.venueInstrumentVersionId}
                      now={priceNow}
                      supported={item.active}
                    />
                  </td>
                  <td class="numeric">{formatBidAsk(item.bestBid, item.bestAsk)[0]}<br />{formatBidAsk(item.bestBid, item.bestAsk)[1]}</td>
                  <td class="numeric">{formatRate(item.fundingRatePerHour)}</td>
                  <td class="numeric optional-column">{formatCompact(item.openInterestNotional)}</td>
                  <td class="numeric optional-column">{metricLabel(metricFor(item)?.oiChange["15m"], 120)} / {metricLabel(metricFor(item)?.oiChange["1h"], 120)}</td>
                  <td class="numeric optional-column">{metricLabel(metricFor(item)?.tradeChange["15m"])} / {metricLabel(metricFor(item)?.tradeChange["1h"])} / {metricLabel(metricFor(item)?.tradeChange["24h"])}</td>
                  <td class="numeric optional-column">
                    {formatCompact(item.volume24hRaw)} {item.volume24hUnit ?? ""}
                  </td>
                  <td>
                    <span class:quality-risk={item.quality !== "ready"}>{statusLabel(item.quality)}</span>
                    <small>{formatAgeSeconds(item.ageSeconds)}</small>
                    <button type="button" class="audit-badge"
                      aria-label={`${item.baseAsset} ${item.venue}の保存足照合を表示`}
                      onclick={() => void openAuditFor(item)}>
                      {auditStatusLabel(auditEntryMap.get(auditTargetKey(item.venueInstrumentId,
                        item.venueInstrumentVersionId)) ?? null, auditIndexStatus)}
                    </button>
                    {#if auditIndexStatus === "unavailable" && auditEntryMap.has(auditTargetKey(item.venueInstrumentId, item.venueInstrumentVersionId))}
                      <small>前回記録 · 更新停止</small>
                    {/if}
                  </td>
                </tr>
              {:else}
                <tr><td colspan="11" class="empty-row">条件に一致するinstrumentはありません</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
      </section>

      <aside class="inspector" aria-labelledby="inspector-title">
        {#if selectedInstrument}
          <div class="instrument-heading">
            <div>
              <p>{selectedInstrument.venue}</p>
              <h2 id="inspector-title">{selectedInstrument.baseAsset} PERP</h2>
              <code>{selectedInstrument.venueInstrumentId}</code>
              <span class="coverage-label">{coverageLabel(selectedInstrument, groupCounts)}</span>
            </div>
            <span class:quality-risk={selectedInstrument.quality !== "ready"}>
              {statusLabel(selectedInstrument.quality)}
            </span>
          </div>

          <section class="daily-change-block" aria-labelledby="daily-change-title">
            <div class="subheading">
              <h3 id="daily-change-title">約定価格の騰落率</h3>
              <span>JST {referenceTime}基準</span>
            </div>
            <PriceChangeValue
              state={priceChanges[selectedInstrument.venueInstrumentId]}
              {referenceTime}
              versionId={selectedInstrument.venueInstrumentVersionId}
              now={priceNow}
              supported={selectedInstrument.active}
              detailed
            />
            <p>指定時刻直前の1分足終値から計算。同じ取引所の約定価格を使用し、約1分ごとに更新します。</p>
          </section>

          <section class="reference-block" aria-labelledby="median-title">
            <h3 id="median-title">参考mark中央値</h3>
            <strong>{formatPrice(selectedInstrument.referenceMarkMedian.value)}</strong>
            <p>Parity仮定・reference only。{selectedInstrument.referenceMarkMedian.venueCount} Venue。</p>
            <p>{market.universe.parityAssumption.statement}</p>
            {#if selectedInstrument.referenceMarkMedian.status !== "ready"}
              <p class="neutral-note">
                算出不能: {reasonLabel(selectedInstrument.referenceMarkMedian.unavailableReason ?? "insufficient_venues")}
              </p>
              <details class="technical-details">
                <summary>技術情報</summary>
                <code>{selectedInstrument.referenceMarkMedian.unavailableReason ?? "reason_missing"}</code>
              </details>
            {/if}
          </section>

          <section class="reference-block" aria-label="追加の市場変化指標">
            <h3>市場変化</h3>
            {#if metricsError}<p role="status">{metricsError}。最後に取得した値の時刻と鮮度を確認してください。</p>{/if}
            {#if selectedMetrics}
              <p>数量OI: 15m {metricLabel(selectedMetrics.oiChange["15m"], 120)} · 1h {metricLabel(selectedMetrics.oiChange["1h"], 120)}</p>
              <p>確定終値: 15m {metricLabel(selectedMetrics.tradeChange["15m"])} · 1h {metricLabel(selectedMetrics.tradeChange["1h"])} · 24h {metricLabel(selectedMetrics.tradeChange["24h"])}</p>
              <p>確定足の共通cutoff: {formatTimestamp(metrics?.candleCutoff ?? null)}。L1と足の鮮度は別々に判定します。</p>
            {:else}
              <p>{metricsError ?? "追加指標は準備中です"}</p>
            {/if}
          </section>

          <section class="l1-block" aria-labelledby="l1-title">
            <div class="subheading"><h3 id="l1-title">Venue L1</h3><span>{selectedInstrument.sourceSymbol}</span></div>
            <dl class="metric-grid">
              <div><dt>Mark</dt><dd>{formatPrice(selectedInstrument.markPrice)}</dd></div>
              <div><dt>Reference</dt><dd>{formatPrice(selectedInstrument.referencePrice)} ({selectedInstrument.referencePriceKind})</dd></div>
              <div><dt>Bid</dt><dd>{formatBidAsk(selectedInstrument.bestBid, selectedInstrument.bestAsk)[0]}</dd></div>
              <div><dt>Ask</dt><dd>{formatBidAsk(selectedInstrument.bestBid, selectedInstrument.bestAsk)[1]}</dd></div>
              <div><dt>Spread</dt><dd>{formatFinite(spreadBps(selectedInstrument.bestBid, selectedInstrument.bestAsk), 2)} bps</dd></div>
              <div><dt>Funding raw</dt><dd>{formatRate(selectedInstrument.fundingRateRaw)}</dd></div>
              <div><dt>Funding / h</dt><dd>{formatRate(selectedInstrument.fundingRatePerHour)}</dd></div>
              <div><dt>Funding周期</dt><dd>{selectedInstrument.fundingIntervalSeconds == null ? "未確認" : `${selectedInstrument.fundingIntervalSeconds / 3600} 時間`}</dd></div>
              <div><dt>次回Funding</dt><dd>{selectedInstrument.nextFundingAt === null ? "未確認" : `${formatTimestamp(selectedInstrument.nextFundingAt)}${Date.parse(selectedInstrument.nextFundingAt) <= priceNow ? " · 経過（次回未確認）" : ""}`}</dd></div>
              <div><dt>OI raw</dt><dd>{formatCompact(selectedInstrument.openInterestRaw)} {selectedInstrument.openInterestRawUnit ?? ""}</dd></div>
              <div><dt>OI notional</dt><dd>{formatCompact(selectedInstrument.openInterestNotional)}</dd></div>
              <div><dt>24h volume</dt><dd>{formatCompact(selectedInstrument.volume24hRaw)} {selectedInstrument.volume24hUnit ?? ""}</dd></div>
              <div><dt>Quote</dt><dd>{selectedInstrument.quoteAsset}</dd></div>
              <div><dt>Settle</dt><dd>{selectedInstrument.settleAsset}</dd></div>
              <div><dt>Collateral</dt><dd>{selectedInstrument.collateralAsset ?? "判定不能"}</dd></div>
            </dl>
            <dl class="provenance">
              <div><dt>observedAt</dt><dd>{formatTimestamp(selectedInstrument.observedAt)}</dd></div>
              <div><dt>sourceAt</dt><dd>{formatTimestamp(selectedInstrument.sourceAt)}</dd></div>
              <div><dt>catalog source</dt><dd>{selectedInstrument.catalog.sourceKind}</dd></div>
              <div><dt>endpoint</dt><dd><code>{selectedInstrument.catalog.endpoint}</code></dd></div>
              <div><dt>payload hash</dt><dd><code>{selectedInstrument.sourcePayloadHash ?? "—"}</code></dd></div>
            </dl>
            {#if selectedInstrument.qualityReasons.length > 0 || selectedInstrument.errorCode}
              <div class="quality-reasons">
                <strong>品質理由</strong>
                <span>{reasonSummary(selectedInstrument.qualityReasons, selectedInstrument.errorCode)}</span>
                <details class="technical-details">
                  <summary>技術情報</summary>
                  <code>{technicalReasonCodes(selectedInstrument.qualityReasons, selectedInstrument.errorCode).join(" / ")}</code>
                </details>
              </div>
            {/if}
          </section>

          <section class="selection-state" aria-live="polite">
            <h3>選択group</h3>
            {#if selectedGroupId}
              <p>{selectedGroupId} / {groupVenueCount} Venue</p>
              <p>行選択は500ms後に反映し、5分ごとに監視leaseを更新します。</p>
              {#if selectionMessage}<p class="quality-good">{selectionMessage}</p>{/if}
              {#if selectionError}<p class="operational-warning" role="alert">{selectionError}</p>{/if}
            {:else}
              <p class="neutral-note">安全に同一groupへ対応できないinstrumentです。板・約定購読は行いません。</p>
            {/if}
          </section>

          {#if selectedInstrument.active}
            <UniverseChart
              venueInstrumentId={selectedVenueInstrumentId!}
              venueInstrumentVersionId={selectedInstrument.venueInstrumentVersionId}
              bind:timeframe={chartTimeframe}
              auditMarkerBuckets={auditIdentityValid && auditDetail ? auditDetail.markerBuckets : []}
              {auditMarkersEnabled}
              onAuditMarkerClick={showAuditFinding}
              {auditJump}
              onAuditJumpResult={(found) => {
                auditJumpMessage = found ? "対応する表示足へ移動しました" : "対応する表示足がありません。過去足を読み込んでください。";
              }}
            />
          {:else}
            <section class="waiting-panel">
              <h3>価格・出来高</h3>
              <p>非activeのためチャートを要求しません</p>
            </section>
          {/if}

          <SourceQualityInspector
            instrument={selectedInstrument}
            bind:open={sourceQualityOpen}
            onOpenChange={setSourceQualityOpen}
            {recovery}
            {recoveryStatus}
            {qualityFetchedAt}
            auditEntry={selectedAuditEntry}
            auditIndexStatus={auditIndexStatus}
            {pinnedAuditRunId}
            {auditDetail}
            {auditIdentityValid}
            {auditDetailError}
            {auditDetailLoading}
            {auditOffset}
            {auditMarkersEnabled}
            {auditJumpMessage}
            onSelectRun={selectAuditRun}
            onPage={(offset) => pinnedAuditRunId && void loadAuditDetail(pinnedAuditRunId, offset)}
            onToggleMarkers={(enabled) => { auditMarkersEnabled = enabled; }}
            onFindingJump={(bucketAt) => {
              auditJump = { bucketAt, sequence: (auditJump?.sequence ?? 0) + 1 };
              auditJumpMessage = null;
            }}
          />

          <section class="selected-market" aria-labelledby="selected-market-title">
            <div class="subheading selected-heading">
              <div><h3 id="selected-market-title">選択groupの板・約定</h3><p>最大20段 / 直近100件</p></div>
              <span class:quality-risk={market.selected.status !== "ready"}>{statusLabel(market.selected.status)}</span>
            </div>
            <p class="disclaimer">{market.selected.disclaimers.statement}</p>
            <p class="disclaimer">手数料を含まず、将来impactを予測せず、表示価格での注文成立を保証しません。</p>
            {#if market.selected.qualityReasons.length > 0}
              <div class="quality-reasons selected-reasons">
                <strong>Selected品質理由</strong>
                <span>{reasonSummary(market.selected.qualityReasons)}</span>
                <details class="technical-details">
                  <summary>技術情報</summary>
                  <code>{technicalReasonCodes(market.selected.qualityReasons).join(" / ")}</code>
                </details>
              </div>
            {/if}

            {#if selectedPayload}
              {#each selectedPayload.instruments as instrument (instrument.venueInstrumentId)}
                <article class="venue-depth">
                  <div class="venue-depth-title">
                    <h4>{instrument.venue} · {instrument.sourceSymbol}</h4>
                    <span class:quality-risk={instrument.quality !== "ready"}>
                      {statusLabel(instrument.quality)} · {formatAgeSeconds(instrument.depthAgeSeconds)}
                    </span>
                  </div>
                  {#if instrument.qualityReasons.length > 0}
                    <div class="quality-reasons">
                      <span>{reasonSummary(instrument.qualityReasons)}</span>
                      <details class="technical-details">
                        <summary>技術情報</summary>
                        <code>{technicalReasonCodes(instrument.qualityReasons).join(" / ")}</code>
                      </details>
                    </div>
                  {/if}

                  <div class="book-walk-scroll">
                    <table class="book-walk-table">
                      <thead><tr><th scope="col">板上概算</th><th scope="col">買い側</th><th scope="col">売り側</th></tr></thead>
                      <tbody>
                        {#each instrument.bookWalks as estimate (estimate.notionalQuote)}
                          <tr>
                            <th scope="row">${formatFinite(estimate.notionalQuote, 0)}</th>
                            <td>
                              {#if estimate.buy}
                                avg {formatPrice(estimate.buy.averagePrice)} / {formatFinite(estimate.buy.topPriceImpactBps, 2)} bps
                              {:else}
                                算出不能: {reasonLabel(estimate.buyUnavailableReason ?? "insufficient_depth")}
                              {/if}
                            </td>
                            <td>
                              {#if estimate.sell}
                                avg {formatPrice(estimate.sell.averagePrice)} / {formatFinite(estimate.sell.topPriceImpactBps, 2)} bps
                              {:else}
                                算出不能: {reasonLabel(estimate.sellUnavailableReason ?? "insufficient_depth")}
                              {/if}
                            </td>
                          </tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>

                  <details>
                    <summary>板 {instrument.bids.length} bid / {instrument.asks.length} ask</summary>
                    <div class="depth-scroll">
                      <table class="depth-table">
                        <thead><tr><th scope="col">Bid size</th><th scope="col">Bid</th><th scope="col">Ask</th><th scope="col">Ask size</th></tr></thead>
                        <tbody>
                          {#each depthRows(instrument) as level, index (index)}
                            <tr>
                              <td>{formatFinite(level.bid?.sizeBase)}</td><td>{formatPrice(level.bid?.price)}</td>
                              <td>{formatPrice(level.ask?.price)}</td><td>{formatFinite(level.ask?.sizeBase)}</td>
                            </tr>
                          {/each}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </article>
              {/each}

              <details class="trades">
                <summary>直近約定 {selectedPayload.trades.length}件</summary>
                <div class="trade-scroll">
                  <table>
                    <thead><tr><th scope="col">時刻</th><th scope="col">Venue</th><th scope="col">side</th><th scope="col">price</th><th scope="col">size</th></tr></thead>
                    <tbody>
                      {#each selectedPayload.trades as trade (`${trade.venueInstrumentId}:${trade.tradeId}`)}
                        <tr>
                          <td>{formatTimestamp(trade.sourceAt)}</td><td>{trade.venue}</td>
                          <td>{trade.side}</td><td>{formatPrice(trade.price)}</td><td>{formatFinite(trade.sizeBase)}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </details>
            {:else}
              <p class="waiting-copy">
                {selectedGroupId
                  ? `選択groupのartifactを待っています: ${reasonSummary(market.selected.qualityReasons)}`
                  : "group未確定のため詳細購読はありません"}
              </p>
            {/if}
          </section>

          <MarketPastNotesPanel venueInstrumentId={selectedInstrument.venueInstrumentId}
            venueInstrumentVersionId={selectedInstrument.venueInstrumentVersionId}
            metricContext={{
              metricGenerationId: selectedMetrics ? metrics?.generationId ?? null : null,
              oi15mPct: metricCurrent(selectedMetrics?.oiChange["15m"], 120),
              trade15mPct: metricCurrent(selectedMetrics?.tradeChange["15m"], 300)
            }} />
        {:else}
          <div class="waiting-panel"><h2 id="inspector-title">Instrument未選択</h2><p>Universeから1行選択してください。</p></div>
        {/if}
      </aside>
    </div>
  {/if}
</main>

<style>
  :global(*) { box-sizing: border-box; }
  .universe-page { min-height: 100vh; padding: var(--space-page); background: var(--bg); color: var(--text); }
  .topbar { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: var(--space-lg); padding: var(--space-sm) 0 var(--space-md); border-bottom: 1px solid var(--line-strong); }
  .ranking-link { align-self: center; color: var(--focus); font-size: var(--type-body-sm-size); text-decoration: none; padding: var(--space-sm) 0; }
  .identity p, .identity h1, .identity span, .section-title h2, .section-title p, .instrument-heading p, .instrument-heading h2, .reference-block h3, .reference-block p, .selection-state h3, .selection-state p, .waiting-panel h2, .waiting-panel h3, .waiting-panel p, .subheading h3, .subheading p, .venue-depth h4, .disclaimer, .waiting-copy { margin: 0; }
  .identity p { color: var(--focus); font-size: var(--type-label-caps-size); font-weight: 800; }
  .identity h1 { margin-top: var(--space-xs); font-size: var(--type-title-lg-size); line-height: var(--type-title-lg-leading); }
  .identity span, .section-title p, .subheading p { display: block; margin-top: var(--space-xs); color: var(--muted); font-size: var(--type-body-sm-size); }
  .preferences { display: flex; flex-wrap: wrap; align-items: end; gap: var(--space-md); }
  .status-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-bottom: 1px solid var(--line-strong); background: var(--surface); }
  .status-strip div { min-width: 0; padding: var(--space-sm) var(--space-md); border-right: 1px solid var(--line); }
  .status-strip span, .status-strip strong { display: block; }
  .status-strip span { color: var(--muted); font-size: var(--type-label-caps-size); }
  .status-strip strong { margin-top: var(--space-xxs); overflow-wrap: anywhere; font-size: var(--type-data-md-size); }
  .operational-banner, .quality-banner { display: grid; gap: var(--space-xxs); padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--warning-border); background: var(--surface); color: var(--warning); font-size: var(--type-body-sm-size); }
  .operational-banner code, .quality-banner code, .technical-details code { display: block; margin-top: var(--space-xs); overflow-wrap: anywhere; color: var(--subtle); }
  .workspace { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(28rem, 1fr); gap: var(--space-grid); margin-top: var(--space-grid); align-items: start; }
  .universe, .inspector { min-width: 0; border: 1px solid var(--line-strong); background: var(--panel-solid); }
  .inspector { position: sticky; top: var(--space-page); max-height: calc(100vh - (2 * var(--space-page))); overflow: auto; }
  .section-title, .instrument-heading, .subheading, .venue-depth-title { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-sm); }
  .section-title { padding: var(--space-md); border-bottom: 1px solid var(--line); }
  .section-title h2, .instrument-heading h2 { font-size: var(--type-heading-md-size); }
  .section-title > strong { color: var(--subtle); font-size: var(--type-data-md-size); }
  .filters { display: grid; grid-template-columns: minmax(12rem, 1fr) repeat(3, minmax(8rem, auto)); gap: var(--space-sm); padding: var(--space-sm) var(--space-md); border-bottom: 1px solid var(--line); background: var(--surface); }
  .filters label { display: grid; gap: var(--space-xs); color: var(--muted); font-size: var(--type-label-caps-size); }
  input, select, .fatal-state button { min-height: var(--control-height-dense); border: 1px solid var(--line-strong); border-radius: var(--radius-none); background: var(--panel-strong); color: var(--text); padding: 0 var(--space-sm); font: inherit; }
  .table-scroll, .book-walk-scroll, .depth-scroll, .trade-scroll { overflow: auto; }
  table { width: 100%; border-collapse: collapse; font-size: var(--type-body-sm-size); }
  th, td { padding: var(--space-sm); border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
  thead th { position: sticky; top: 0; z-index: 1; background: var(--panel-strong); color: var(--muted); font-size: var(--type-label-caps-size); }
  tbody tr.selected { background: var(--panel-selected); box-shadow: inset 3px 0 var(--focus); }
  .instrument-select { display: grid; gap: var(--space-xxs); width: 100%; min-height: var(--control-height-dense); border: 0; background: transparent; color: var(--text); padding: 0; font: inherit; text-align: left; cursor: pointer; }
  .instrument-select strong { font-size: var(--type-data-md-size); }
  .instrument-select span, td small, .coverage-label { display: block; color: var(--muted); font-size: var(--type-label-caps-size); }
  .audit-badge { display: block; min-height: 44px; border: 0; background: transparent; color: var(--focus); padding: var(--space-xs) 0; text-align: left; font: inherit; font-size: var(--type-label-caps-size); cursor: pointer; overflow-wrap: anywhere; }
  .audit-badge:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  .coverage-label { margin-top: var(--space-xxs); color: var(--subtle); }
  .numeric, dd, code { font-variant-numeric: tabular-nums; }
  .mobile-change { display: none; }
  .change-column small { display: block; margin-top: var(--space-xxs); font: inherit; white-space: nowrap; }
  .daily-change-block { padding: var(--space-md); border-bottom: 1px solid var(--line); }
  .daily-change-block h3 { margin: 0; font-size: var(--type-heading-md-size); }
  .daily-change-block > :global(.price-change) { display: block; margin-top: var(--space-sm); }
  .daily-change-block p { margin: var(--space-sm) 0 0; color: var(--muted); font-size: var(--type-body-sm-size); line-height: var(--type-body-sm-leading); }
  .empty-row { padding: var(--space-xl); color: var(--muted); text-align: center; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
  .instrument-heading { padding: var(--space-md); border-bottom: 1px solid var(--line-strong); background: var(--panel-selected); }
  .instrument-heading p { color: var(--focus); font-size: var(--type-label-caps-size); font-weight: 800; }
  .instrument-heading h2 { margin-top: var(--space-xs); font-size: var(--type-title-lg-size); }
  .instrument-heading code { display: block; margin-top: var(--space-xs); color: var(--subtle); font: inherit; font-size: var(--type-body-sm-size); }
  .reference-block, .l1-block, .selection-state, .waiting-panel { padding: var(--space-md); border-bottom: 1px solid var(--line); }
  .reference-block strong { display: block; margin-top: var(--space-sm); font-size: var(--type-data-lg-size); }
  .reference-block p, .selection-state p, .waiting-panel p, .disclaimer, .waiting-copy { margin-top: var(--space-xs); color: var(--muted); font-size: var(--type-body-sm-size); line-height: var(--type-body-sm-leading); }
  .metric-grid, .provenance { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: var(--space-sm) 0 0; }
  .metric-grid div, .provenance div { min-width: 0; padding: var(--space-sm); border-top: 1px solid var(--line); }
  dt { color: var(--muted); font-size: var(--type-label-caps-size); }
  dd { margin: var(--space-xxs) 0 0; overflow-wrap: anywhere; font-size: var(--type-data-md-size); }
  .provenance dd { font-size: var(--type-body-sm-size); }
  .provenance code { font: inherit; }
  .quality-reasons { display: grid; gap: var(--space-xxs); margin-top: var(--space-sm); padding: var(--space-sm); border-left: 2px solid var(--quality-risk); color: var(--quality-risk); font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
  .quality-risk { color: var(--quality-risk) !important; }
  .quality-good { color: var(--quality-good) !important; }
  .operational-warning { color: var(--warning); }
  .neutral-note { color: var(--muted); }
  .technical-details { margin-top: var(--space-xs); color: var(--subtle); }
  .selected-market { border-bottom: 1px solid var(--line); }
  .selected-heading, .selected-market > .disclaimer, .selected-market > .selected-reasons, .selected-market > .waiting-copy { padding-right: var(--space-md); padding-left: var(--space-md); }
  .selected-heading { padding-top: var(--space-md); }
  .disclaimer { color: var(--warning); }
  .venue-depth { padding: var(--space-md); border-top: 1px solid var(--line-strong); }
  .venue-depth h4 { font-size: var(--type-heading-md-size); }
  .venue-depth-title span, .subheading > span { color: var(--subtle); font-size: var(--type-body-sm-size); }
  .book-walk-table, .depth-table { min-width: 34rem; margin-top: var(--space-sm); }
  details { margin-top: var(--space-sm); }
  summary { min-height: var(--control-height-dense); padding: var(--space-sm) 0; color: var(--subtle); cursor: pointer; font-size: var(--type-body-sm-size); }
  .trades { margin: 0; padding: 0 var(--space-md) var(--space-md); border-top: 1px solid var(--line); }
  .trade-scroll table { min-width: 34rem; }
  .fatal-state { max-width: 48rem; margin: 12vh auto; padding: var(--space-xl); border: 1px solid var(--quality-risk); background: var(--panel-solid); }
  .fatal-state p { color: var(--quality-risk); }
  .fatal-state button { margin-top: var(--space-md); cursor: pointer; }
  @media (max-width: 80rem) {
    .workspace { grid-template-columns: 1fr; }
    .inspector { position: static; max-height: none; overflow: visible; }
  }
  @media (max-width: 60rem) {
    .filters { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .search-control { grid-column: 1 / -1; }
    .table-scroll { max-height: 55vh; }
  }
  @media (max-width: 48rem) {
    .universe-page { padding: var(--space-sm); }
    .topbar, .preferences { align-items: stretch; flex-direction: column; }
    .preferences { display: grid; grid-template-columns: 1fr; }
    .status-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .status-strip div:nth-child(5) { grid-column: 1 / -1; }
    .filters { grid-template-columns: 1fr; }
    .search-control { grid-column: auto; }
    input, select, .instrument-select, summary, .fatal-state button { min-height: var(--control-height-touch); }
    .optional-column { display: none; }
    .change-column { display: none; }
    .mobile-change { display: block; margin-top: var(--space-xs); }
    th, td { padding: var(--space-sm) var(--space-xs); }
    .instrument-select span { max-width: 9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .metric-grid, .provenance { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .section-title, .instrument-heading, .subheading, .venue-depth-title { align-items: flex-start; }
  }
</style>
