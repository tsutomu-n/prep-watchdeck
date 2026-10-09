<script lang="ts">
  import { currentPreferences, preferences } from "$lib/theme/workspace-preferences";
  import { onMount, tick, untrack } from "svelte";
  import { page } from "$app/state";
  import { pushState, replaceState } from "$app/navigation";
  import { subscribeReferenceTime, subscribeTurnoverDecimals } from "$lib/theme/display-preferences";
  import { DEFAULT_TURNOVER_DECIMALS, formatTurnover } from "$lib/market/turnover-format";
  import MarketPastNotesPanel from "$lib/components/universe/MarketPastNotesPanel.svelte";
  import ReferenceChart from "$lib/components/ranking/ReferenceChart.svelte";
  import RosterNotice from "$lib/components/ranking/RosterNotice.svelte";
  import RelativeVolumeSignal from "$lib/components/ranking/RelativeVolumeSignal.svelte";
  import NativeActivitySignal from "$lib/components/ranking/NativeActivitySignal.svelte";
  import NativeActivityDetails from "$lib/components/ranking/NativeActivityDetails.svelte";
  import { nativeActivity, nativeActivityKind } from "$lib/market/native-activity";
  import type { NativeActivityArtifact } from "$lib/generated/native-activity";
  import RelativeVolumeDetails from "$lib/components/ranking/RelativeVolumeDetails.svelte";
  import type { RankedRow, RankingResponse } from "$lib/generated/ranking-response";
  import type { UniverseSnapshotArtifact } from "$lib/generated/universe-snapshot";
  import { venueTurnover, formatVenueTurnover } from "$lib/market/venue-turnover";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import { filterSortRankingRows, type RankingSort } from "$lib/market/market-view";
  import { newlyIncreasedRows, relativeVolumeState } from "$lib/market/relative-volume";
  import { formatPrice } from "$lib/market/universe-view";
  import { favoriteKey, readUserWorkspace, setFavorite } from "$lib/market/user-workspace";
  import { recordRecentMarket } from "$lib/market/recent-markets";
  import {
    browserRankingSession, rankingPreferenceKey, rankingSnapshotExpired, type RankingSession
  } from "$lib/market/ranking-session";
  import { nativeUniverseFresh, referenceNativeCandidates } from "$lib/market/ranking-native";
  import AssetIcon from "$lib/components/AssetIcon.svelte";
  import type { FavoriteTarget, UserWorkspace } from "$lib/server/user-workspace-repository";
  import { DEFAULT_REFERENCE_TIME, formatPriceChange as baseFormatPriceChange } from "$lib/market/price-change";
  import {
    CHART_INTERVAL_KEY, RANKING_MAX_AGE_MS, approvedWidgetSymbol, indicatorLabel as baseIndicatorLabel, matchesRankingQuery,
    rankChangeLabel, rankingQuery, rankingRowStateLabel, rankingStateLabel, rankingTimestamp, readChartInterval, referenceLabel,
    turnoverLabel, type ChartInterval, type RankingOrder, type RankingPeriod
  } from "$lib/market/ranking";

  let { market, legacyEntry = false }: {
    market: MarketArtifactBundle | null; legacyEntry?: boolean;
  } = $props();
  const formatPriceChange = (value: number) => baseFormatPriceChange(value, $preferences.percentDecimals);
  const indicatorLabel = (value: Parameters<typeof baseIndicatorLabel>[0], unit: "倍" | "%") =>
    baseIndicatorLabel(value, unit, unit === "倍" ? $preferences.ratioDecimals : $preferences.percentDecimals);
  let startupCancelled = false;
  let startupViewPending = true;
  let startupUrl = "";
  let noteTargetId = $state("");
  let period = $state<RankingPeriod>("15m");
  let order = $state<RankingOrder>("gainers");
  let reference = $state(DEFAULT_REFERENCE_TIME);
  let referenceReady = $state(false);
  let minimum = $state(0);
  let turnoverDecimals = $state(DEFAULT_TURNOVER_DECIMALS);
  let search = $state("");
  let includeUnranked = $state(false);
  let venue = $state<"all" | "bitget" | "hyperliquid" | "aster">("all");
  let minRatio = $state<number | null>(null);
  let ratioPeriod = $state<"15m" | "1h">("15m");
  let minDayPosition = $state<number | null>(null);
  let maxDayPosition = $state<number | null>(null);
  let sort = $state<RankingSort>("server");
  let direction = $state<"asc" | "desc">("asc");
  let preset = $state<"standard" | "movement">("standard");
  let lockedIds = $state<string[] | null>(null);
  let favoritesOnly = $state(false);
  let workspace = $state<UserWorkspace | null>(null);
  let workspaceError = $state<string | null>(null);
  let favoriteBusy = $state<Set<string>>(new Set());
  let favoriteIntent = $state<Record<string, boolean>>({});
  let viewName = $state("");
  let selectedViewId = $state("");
  let viewBusy = $state(false);
  let limit = $state(50);
  let interval = $state<ChartInterval>("15");
  let data = $state<RankingResponse | null>(null);
  let newVolumeRows = $state<Set<string>>(new Set());
  let lastSelected = $state<RankedRow | null>(null);
  let selectedId = $state<string | null>(null);
  let selectedRemoved = $state(false);
  let mounted = $state(false);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let refreshFailed = $state(false);
  let storageMessage = $state<string | null>(null);
  let now = $state(Date.now());
  let activityData = $state<NativeActivityArtifact | null>(null);
  let nativeUniverse = $state<UniverseSnapshotArtifact | null>(null);
  let nativeLoading = $state(false);
  let nativeError = $state<string | null>(null);
  let cachedSnapshot = $state(false);
  let session: RankingSession | null = null;
  let entryId = "";
  let sessionPreferenceKey = "";
  let restoredView = false;
  let restoredPageTop: number | null = null;
  let tableScroll: HTMLDivElement;
  let listScroll = $state({ top: 0, left: 0 });
  let restoreList = $state(false);
  let restoredScroll = { top: 0, left: 0 };
  let mobile = $state(false);
  const detailHistory = $derived(Boolean((page.state as { referenceDetail?: boolean }).referenceDetail));
  const mobileDetail = $derived(mobile && detailHistory);
  let wasDetail = false;
  let listPageTop = 0;
  let mobileListScroll = { top: 0, left: 0 };
  let mobileListOrigin = false;
  let detailBack: HTMLButtonElement;

  const needsNativeUniverse = $derived(mounted &&
    (venue === "bitget" || venue === "hyperliquid" || selectedId !== null));
  $effect(() => {
    if (!needsNativeUniverse) return;
    nativeUniverse = untrack(() => market?.universe ?? null);
    let disposed = false;
    let pending = false;
    let request: AbortController | null = null;
    const refreshNative = async () => {
      if (pending || document.hidden) return;
      pending = true;
      nativeLoading = true;
      nativeError = null;
      request = new AbortController();
      const timeout = setTimeout(() => request?.abort(), 10_000);
      try {
        const response = await fetch("/api/market-data", { cache: "no-store", signal: request.signal });
        if (!response.ok) throw new Error("市場データを取得できません");
        const payload: MarketArtifactBundle = await response.json();
        if (!payload.universe || !Array.isArray(payload.universe.items)) throw new Error("invalid universe");
        if (!disposed) { nativeUniverse = payload.universe; now = Date.now(); }
      } catch {
        if (!disposed) {
          nativeUniverse = null;
          nativeError = "現在の取扱い情報を取得できません。更新後に再確認します。";
        }
      } finally {
        clearTimeout(timeout); pending = false;
        if (!disposed) nativeLoading = false;
      }
    };
    const visible = () => { now = Date.now(); void refreshNative(); };
    void refreshNative();
    const timer = setInterval(refreshNative, 15_000);
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true; request?.abort(); clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  });

  $effect(() => {
    if (!mounted || venue !== "bitget") return;
    activityData = null;
    let disposed = false;
    let pending = false;
    let request: AbortController | null = null;
    const refreshActivity = async () => {
      if (pending || document.hidden) return;
      pending = true;
      request = new AbortController();
      const timeout = setTimeout(() => request?.abort(), 10_000);
      try {
        const response = await fetch("/api/native-activity", { cache: "no-store", signal: request.signal });
        if (!response.ok) throw new Error("native activity unavailable");
        const payload: NativeActivityArtifact = await response.json();
        if (!Array.isArray(payload.rows)) throw new Error("invalid native activity");
        if (!disposed) { activityData = payload; now = Date.now(); }
      } catch {
        if (!disposed) activityData = null;
      } finally { clearTimeout(timeout); pending = false; }
    };
    const visible = () => { now = Date.now(); void refreshActivity(); };
    void refreshActivity();
    const timer = setInterval(refreshActivity, 15_000);
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true; request?.abort(); clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  });
  $effect(() => {
    if (mounted && venue !== "bitget" && (sort === "nativeRatio15m" || sort === "nativeRatio1h")) {
      sort = sort === "nativeRatio15m" ? "ratio15m" : "ratio1h";
    }
  });

  function hasViewQuery(params: URLSearchParams) {
    return [...params.keys()].some(key => key !== "mode");
  }
  // Changing the rule does not create a market-arrival notification.
  $effect(() => { void $preferences.surgeRatio; void $preferences.directionPct; newVolumeRows = new Set(); });

  function boundedNumber(value: string | null, maximum = Number.MAX_SAFE_INTEGER) {
    if (value === null || value.trim() === "") return null;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 && number <= maximum ? number : null;
  }
  let controller: AbortController | null = null;
  let requestId = 0;
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;

  const query = $derived.by(() => {
    try { return rankingQuery(period, reference, order, minimum).toString(); }
    catch { return null; }
  });
  const selected = $derived(data?.rows.find((row) => row.id === selectedId) ?? lastSelected);
  const nativeCandidates = $derived(referenceNativeCandidates(selected, nativeUniverse, now));
  let noteTarget = $derived(nativeCandidates.find(item => item.venueInstrumentId === noteTargetId) ?? nativeCandidates[0]);
  const symbol = $derived(selectedRemoved ? null : approvedWidgetSymbol(selected));
  const stale = $derived(Boolean(data && (refreshFailed || rankingSnapshotExpired(data, now))));
  const comparisonExpired = $derived(stale || Boolean(data?.previousCutoff && now - data.previousCutoff > RANKING_MAX_AGE_MS));
  const newVolumeVisible = $derived(Boolean(data && !stale && now - data.generatedAt < 60_000));
  const nativeViews = $derived(new Map((data?.rows ?? []).map(row => [row.id, nativeActivity(row, activityData, now)])));
  const nativeRatios = $derived(new Map([...nativeViews].map(([id, view]) => [id, {
    "15m": view.row?.windows["15m"].relativeRatio.value ?? null,
    "1h": view.row?.windows["1h"].relativeRatio.value ?? null
  }])));
  const visibleRows = $derived.by(() => {
    const current = filterSortRankingRows(data?.rows ?? [], {
      search, venue, includeUnranked, minRatio, ratioPeriod, minDayPosition, maxDayPosition,
      sort, direction
    }, nativeRatios).filter((row) => !favoritesOnly || Boolean(
      workspace?.favorites.some((entry) => entry.kind === "reference" && entry.id === row.id)
    ));
    if (!lockedIds) return current;
    const byId = new Map(current.map((row) => [row.id, row]));
    return lockedIds.flatMap((id) => {
      const row = byId.get(id);
      return row ? [row] : [];
    });
  });
  const addedRows = $derived(lockedIds ? Math.max(0,
    filterSortRankingRows(data?.rows ?? [], {
      search, venue, includeUnranked, minRatio, ratioPeriod, minDayPosition, maxDayPosition,
      sort, direction
    }, nativeRatios).length - visibleRows.length) : 0);
  const volumeSpotlight = $derived.by(() => {
    if (!data || stale) return [];
    // Direction ranking affects table ranks, not discovery of the opposite direction.
    const candidates = filterSortRankingRows(data.rows, {
      search, venue, includeUnranked: true, minRatio, ratioPeriod, minDayPosition, maxDayPosition,
      sort: "asset", direction: "asc"
    }).filter(row => (!favoritesOnly || Boolean(
      workspace?.favorites.some(entry => entry.kind === "reference" && entry.id === row.id)
    )) && row.turnoverComparison.current.quoteTurnover !== null
      && row.turnoverComparison.current.quoteTurnover >= minimum)
      .map(row => ({ row, signal: relativeVolumeState(row, false, $preferences) }));
    const groups = (["up", "down", "volume"] as const).map(kind => candidates
      .filter(item => item.signal.kind === kind)
      .sort((a, b) => (b.signal.strength! - a.signal.strength!) || a.row.id.localeCompare(b.row.id))
      .slice(0, 3).map(item => item.row));
    return [0, 1, 2].flatMap(index => groups.flatMap(group => group[index] ? [group[index]] : []));
  });
  const selectedFiltered = $derived(Boolean(selectedId && data && !visibleRows.some((row) => row.id === selectedId)));
  const quantityUnverified = $derived((data?.rows ?? []).reduce((count, row) =>
    count + row.originals.filter((item) => item.multiplier === null).length, 0));
  const widgetReview = $derived((data?.rows ?? []).filter((row) => row.widget.status === "review").length);
  const orderLabel = $derived(order === "gainers" ? "上昇率順" : order === "losers" ? "下落率順" : "売買代金順");
  const periodLabel = $derived(period === "15m" ? "15分" : period === "1h" ? "1時間"
    : period === "24h" ? "直近24時間" : `JST ${reference}基準`);
  const viewSortLabels: Record<RankingSort, string> = {
    server: "全体順位", asset: "銘柄名", referenceClose: "参照終値", returnPct: "騰落率",
    quoteTurnover: "売買代金", return15m: "15分騰落率", return1h: "1時間騰落率",
    return24h: "24時間騰落率", ratio15m: "15分平常比", ratio1h: "1時間平常比",
    nativeRatio15m: "Bitget 15分普段比", nativeRatio1h: "Bitget 1時間普段比",
    dayPosition: "当日位置"
  };
  const activeConditions = $derived([
    minimum > 0 ? `売買代金 ${minimum.toLocaleString("en-US")} USDT以上` : "",
    search.trim() ? `検索: ${search.trim()}` : "", favoritesOnly ? "お気に入りのみ" : "",
    venue !== "all" ? `取扱い: ${venue === "hyperliquid" ? "Hyperliquid" : venue === "bitget" ? "Bitget" : "Aster"}` : "",
    includeUnranked ? "順位外・未対応を含む" : "",
    minRatio !== null ? `${ratioPeriod === "15m" ? "15分" : "1時間"}平常比 ${minRatio}倍以上` : "",
    minDayPosition !== null ? `当日位置 ${minDayPosition}%以上` : "",
    maxDayPosition !== null ? `当日位置 ${maxDayPosition}%以下` : "",
    sort !== "server" || direction !== "asc" ? `一覧: ${viewSortLabels[sort]}${direction === "desc" ? "降順" : "昇順"}` : "",
    lockedIds ? "行順固定中" : "", preset === "movement" ? "値動き列" : ""
  ].filter(Boolean));

  function mobileSortBasis(row: RankedRow) {
    if (sort === "referenceClose") return `参照終値 ${row.referenceClose.status === "ready" ? formatPrice(row.referenceClose.value) : "未取得"}`;
    if (sort === "return15m" || sort === "return1h" || sort === "return24h") {
      const window = sort === "return15m" ? "15m" : sort === "return1h" ? "1h" : "24h";
      const value = row.windows[window].returnPct;
      return `${viewSortLabels[sort]} ${value === null ? "未取得" : formatPriceChange(value)}`;
    }
    if (sort === "ratio15m" || sort === "ratio1h") {
      return `${viewSortLabels[sort]} ${indicatorLabel(row.turnoverRatios[sort === "ratio15m" ? "15m" : "1h"], "倍")}`;
    }
    if (sort === "nativeRatio15m" || sort === "nativeRatio1h") {
      const value = nativeRatios.get(row.id)?.[sort === "nativeRatio15m" ? "15m" : "1h"];
      return `${viewSortLabels[sort]} ${value === null || value === undefined ? "—" : `${value.toFixed($preferences.ratioDecimals)}倍`}`;
    }
    if (sort === "dayPosition") return `当日位置 ${indicatorLabel(row.dayRangePosition, "%")}`;
    return "";
  }

  async function refresh(parameters: string) {
    if (!mounted || document.hidden) return;
    controller?.abort();
    const request = new AbortController();
    controller = request;
    const current = ++requestId;
    loading = true; error = null;
    try {
      const response = await fetch(`/api/rankings?${parameters}`, { signal: request.signal });
      if (!response.ok) throw new Error("ランキングの更新を待っています。専用収集の起動・取得状況を確認してください。");
      const payload: RankingResponse = await response.json();
      if (current !== requestId || !mounted || request.signal.aborted) return;
      if (!matchesRankingQuery(payload, new URLSearchParams(parameters))) {
        throw new Error("取得したランキングの条件が一致しません。再試行してください。");
      }
      now = Date.now();
      if (payload.generationId !== data?.generationId) {
        newVolumeRows = newlyIncreasedRows(data, payload, now, $preferences);
      }
      session?.rememberResult(parameters, payload);
      data = payload;
      cachedSnapshot = false;
      refreshFailed = false;
      if (selectedId) {
        const updated = payload.rows.find((row) => row.id === selectedId);
        selectedRemoved = !updated;
        if (updated) lastSelected = updated;
      }
    } catch (cause) {
      if (mounted && current === requestId && !(cause instanceof DOMException && cause.name === "AbortError")) {
        error = cause instanceof Error ? cause.message : "ランキングを取得できませんでした";
        refreshFailed = true;
      }
    } finally { if (current === requestId) loading = false; }
  }

  function schedule() {
    const time = Date.now();
    let target = Math.floor(time / 60_000) * 60_000 + 12_000;
    if (target <= time) target += 60_000;
    refreshTimer = setTimeout(() => {
      if (mounted && !document.hidden && query) void refresh(query);
      schedule();
    }, target - time);
  }

  onMount(() => {
    const initial = currentPreferences();
    session = browserRankingSession();
    const historyEntryId = page.state.rankingSessionEntry;
    // The list and its shallow detail entry share an identity across component remounts.
    entryId = historyEntryId ?? crypto.randomUUID();
    startupUrl = page.url.href;
    const cancelStartup = () => { startupCancelled = true; };
    const interactionEvents = ["pointerdown", "keydown", "input", "change"];
    for (const event of interactionEvents) document.addEventListener(event, cancelStartup, { once: true });
    const stopReference = subscribeReferenceTime((value) => {
      reference = value; referenceReady = true;
      sessionPreferenceKey = rankingPreferenceKey(currentPreferences(), value);
    });
    const stopTurnover = subscribeTurnoverDecimals(value => { turnoverDecimals = value; });
    const width = window.matchMedia("(max-width: 960px)");
    const updateWidth = () => mobile = width.matches;
    updateWidth(); width.addEventListener("change", updateWidth);
    const loadWorkspace = () => {
      if (document.visibilityState !== "hidden") {
        void readUserWorkspace().then((value) => { workspace = value; workspaceError = null;
          if (startupViewPending) {
            startupViewPending = false;
            if (!startupCancelled && page.url.href === startupUrl && initial.referenceViewId
              && !hasViewQuery(page.url.searchParams)) {
              if (value.savedViews.some(view => view.id === initial.referenceViewId && view.view.mode === "reference")) applySavedView(initial.referenceViewId);
              else workspaceError = "初期表示に指定した保存表示が見つかりません。初期値を使っています。";
            }
          } })
          .catch(() => workspaceError = "お気に入りを読み込めません");
      }
    };
    loadWorkspace();
    document.addEventListener("visibilitychange", loadWorkspace);
    if (!legacyEntry) {
      period = "24h";
      order = "turnover";
    }
    if (initial.initialPeriod !== "default") period = initial.initialPeriod;
    if (initial.initialOrder !== "default") order = initial.initialOrder;
    preset = initial.initialColumns;
    const params = page.url.searchParams;
    const saved = session?.restoreView(sessionPreferenceKey, params, historyEntryId, legacyEntry);
    if (saved) {
      period = saved.period; order = saved.order; reference = saved.reference; minimum = saved.minimum;
      search = saved.search; venue = saved.venue; includeUnranked = saved.includeUnranked;
      favoritesOnly = saved.favoritesOnly; ratioPeriod = saved.ratioPeriod; minRatio = saved.minRatio;
      minDayPosition = saved.minDayPosition; maxDayPosition = saved.maxDayPosition;
      sort = saved.sort; direction = saved.direction; preset = saved.preset;
      lockedIds = saved.lockedIds; selectedId = saved.selectedId; lastSelected = saved.lastSelected;
      selectedRemoved = saved.selectedRemoved; noteTargetId = saved.noteTargetId;
      selectedViewId = saved.selectedViewId; viewName = saved.viewName; workspace = saved.workspace;
      limit = saved.limit; restoredScroll = saved.listScroll; listScroll = saved.listScroll;
      restoredPageTop = saved.pageTop;
      // Menu entry resumes the list; only Back to the same history entry resumes detail.
      restoreList = !saved.detailOpen || historyEntryId !== saved.entryId;
      mobileListScroll = saved.listScroll; listPageTop = saved.pageTop;
      mobileListOrigin = true;
      restoredView = true; startupViewPending = false;
    }
    try { if (!saved || (hasViewQuery(params) && historyEntryId !== saved.entryId)) {
      const requestedPeriod = params.get("period") as RankingPeriod | null;
      const requestedOrder = params.get("order") as RankingOrder | null;
      const requestedReference = params.get("dailyReferenceJst");
      const requestedMinimum = params.get("minTurnover");
      if (requestedPeriod || requestedOrder || requestedReference || requestedMinimum !== null) {
        rankingQuery(requestedPeriod ?? period, requestedReference ?? reference,
          requestedOrder ?? order, requestedMinimum === null ? minimum : Number(requestedMinimum));
        period = requestedPeriod ?? period;
        order = requestedOrder ?? order;
        reference = requestedReference ?? reference;
        minimum = requestedMinimum === null ? minimum : Number(requestedMinimum);
      }
      search = params.get("q") ?? "";
      const requestedVenue = params.get("venue");
      if (["all", "bitget", "hyperliquid", "aster"].includes(requestedVenue ?? "")) {
        venue = requestedVenue as typeof venue;
      }
      includeUnranked = params.get("includeUnranked") === "1";
      favoritesOnly = params.get("favoritesOnly") === "1";
      const requestedSort = params.get("sort");
      if (requestedSort && ["server", "asset", "referenceClose", "returnPct", "quoteTurnover",
        "return15m", "return1h", "return24h", "ratio15m", "ratio1h", "nativeRatio15m", "nativeRatio1h", "dayPosition"].includes(requestedSort)) {
        sort = requestedSort as RankingSort;
      }
      direction = params.get("direction") === "desc" ? "desc" : "asc";
      ratioPeriod = params.get("ratioPeriod") === "1h" ? "1h" : "15m";
      minRatio = boundedNumber(params.get("minRatio"));
      minDayPosition = boundedNumber(params.get("minDayPosition"), 100);
      maxDayPosition = boundedNumber(params.get("maxDayPosition"), 100);
      if (params.has("preset")) preset = params.get("preset") === "movement" ? "movement" : "standard";
      restoredScroll = {
        top: boundedNumber(params.get("listTop")) ?? 0,
        left: boundedNumber(params.get("listLeft")) ?? 0
      };
      restoreList = params.get("restoreList") === "1";
    } } catch { /* Invalid legacy query leaves safe defaults visible. */ }
    const selectedFromUrl = params.get("selected");
    if (selectedFromUrl && /^[A-Za-z0-9:._-]{1,160}$/.test(selectedFromUrl)) {
      selectedId = selectedFromUrl;
    }
    try { interval = saved?.interval ?? readChartInterval(window.localStorage); }
    catch { interval = saved?.interval ?? "15"; }
    if (initial.chartInterval !== "last") interval = initial.chartInterval;
    let detailTimer: ReturnType<typeof setTimeout> | undefined;
    if (mobile && selectedId && !restoreList && !detailHistory) {
      const initialUrl = page.url.href;
      const initialSelected = selectedId;
      detailTimer = setTimeout(() => {
        if (mounted && mobile && !restoreList && selectedId === initialSelected &&
          page.url.href === initialUrl && !detailHistory) {
          replaceState("", { ...page.state, rankingSessionEntry: entryId, referenceDetail: false });
          pushState("", { ...page.state, rankingSessionEntry: entryId, referenceDetail: true });
        }
      }, 0);
    }
    mounted = true;
    // Defer shallow routing until the router has finished hydration, as for mobile detail.
    const entryTimer = setTimeout(() => {
      if (mounted && page.url.href === startupUrl) {
        replaceState("", { ...page.state, rankingSessionEntry: entryId });
      }
    }, 0);
    const clock = setInterval(() => now = Date.now(), 10_000);
    const visible = () => {
      now = Date.now();
      if (document.hidden) {
        requestId += 1; controller?.abort(); loading = false;
      } else if (query) void refresh(query);
    };
    document.addEventListener("visibilitychange", visible);
    schedule();
    return () => {
      session?.rememberView(sessionPreferenceKey, {
        entryId, period, order, reference, minimum, search, venue, includeUnranked, favoritesOnly,
        ratioPeriod, minRatio, minDayPosition, maxDayPosition, sort, direction, preset,
        lockedIds: lockedIds?.slice() ?? null, selectedId, lastSelected: $state.snapshot(lastSelected),
        selectedRemoved, noteTargetId, selectedViewId, viewName, interval, limit,
        listScroll: mobile && wasDetail ? mobileListScroll : { ...listScroll },
        pageTop: mobile && wasDetail ? listPageTop : window.scrollY,
        detailOpen: mobile && wasDetail, workspace: $state.snapshot(workspace)
      });
      mounted = false; clearTimeout(detailTimer); clearTimeout(entryTimer);
      for (const event of interactionEvents) document.removeEventListener(event, cancelStartup);
      stopReference(); stopTurnover(); width.removeEventListener("change", updateWidth);
      requestId += 1; controller?.abort(); clearTimeout(refreshTimer); clearInterval(clock);
      document.removeEventListener("visibilitychange", visible);
      document.removeEventListener("visibilitychange", loadWorkspace);
    };
  });

  async function restoreMobileList() {
    const index = visibleRows.findIndex((row) => row.id === selectedId);
    if (index >= limit) limit = Math.ceil((index + 1) / 50) * 50;
    await tick();
    if (tableScroll) {
      tableScroll.scrollTop = mobileListScroll.top;
      tableScroll.scrollLeft = mobileListScroll.left;
      tableScroll.querySelector<HTMLButtonElement>('button.select-row[aria-pressed="true"]')
        ?.focus({ preventScroll: mobileListOrigin });
    }
    if (mobileListOrigin) window.scrollTo({ top: listPageTop, behavior: "instant" });
  }

  $effect(() => {
    const showingDetail = detailHistory;
    if (!mounted) return;
    if (!wasDetail && showingDetail && untrack(() => mobile)) {
      untrack(() => void tick().then(() => detailBack?.focus({ preventScroll: true })));
    }
    if (wasDetail && !showingDetail && untrack(() => mobile)) untrack(() => void restoreMobileList());
    wasDetail = showingDetail;
  });

  $effect(() => {
    if (!mounted || !referenceReady || !query) return;
    const parameters = query;
    untrack(() => {
      if (!restoredView) limit = 50;
      restoredView = false;
      now = Date.now();
      const cached = session?.readResult(parameters, now);
      data = cached?.data ?? null;
      cachedSnapshot = Boolean(cached);
      newVolumeRows = new Set();
      error = null;
      refreshFailed = false;
      if (data && selectedId) {
        const updated = data.rows.find(row => row.id === selectedId);
        selectedRemoved = !updated;
        if (updated) lastSelected = updated;
      }
      void refresh(parameters);
    });
  });

  $effect(() => {
    if (!mounted) return;
    try { window.localStorage.setItem(CHART_INTERVAL_KEY, interval); storageMessage = null; }
    catch { storageMessage = "チャートの足設定は、この画面だけに適用しています"; }
  });

  $effect(() => {
    if (!restoreList || !data || (favoritesOnly && !workspace)) return;
    const index = visibleRows.findIndex(row => row.id === selectedId);
    untrack(() => {
      restoreList = false;
      if (index >= limit) limit = Math.ceil((index + 1) / 50) * 50;
      void tick().then(() => {
        const selectedButton = tableScroll?.querySelector<HTMLButtonElement>(
          'button.select-row[aria-pressed="true"]'
        );
        selectedButton?.focus({ preventScroll: true });
        if (tableScroll) {
          tableScroll.scrollTop = restoredScroll.top;
          tableScroll.scrollLeft = restoredScroll.left;
        }
        if (restoredPageTop !== null) {
          window.scrollTo({ top: restoredPageTop, behavior: "instant" });
          restoredPageTop = null;
        }
      });
    });
  });

  async function select(row: RankedRow) {
    const selectionUrl = new URL(page.url);
    selectionUrl.searchParams.set("selected", row.id);
    selectionUrl.searchParams.delete("restoreList");
    if (mobile && !mobileDetail) {
      mobileListOrigin = true;
      listPageTop = window.scrollY;
      mobileListScroll = { top: tableScroll?.scrollTop ?? 0, left: tableScroll?.scrollLeft ?? 0 };
      replaceState(selectionUrl, { ...page.state, rankingSessionEntry: entryId, referenceDetail: false });
      pushState(selectionUrl, { ...page.state, rankingSessionEntry: entryId, referenceDetail: true });
    } else {
      replaceState(selectionUrl, { ...page.state, rankingSessionEntry: entryId });
    }
    selectedId = row.id; lastSelected = row; selectedRemoved = false;
    try {
      recordRecentMarket(window.localStorage, {
        key: `reference:${row.id}`, label: `${row.asset} · 参照市場`,
        href: `/?mode=reference&selected=${encodeURIComponent(row.id)}`
      });
    } catch { /* The current selection remains usable without browser storage. */ }
    await tick();
    if (mobile) {
      window.scrollTo({ top: 0, behavior: "instant" });
      detailBack?.focus({ preventScroll: true });
    }
  }

  function chooseSort(column: RankingSort) {
    if (sort === column) direction = direction === "asc" ? "desc" : "asc";
    else {
      sort = column;
      direction = ["referenceClose", "returnPct", "quoteTurnover", "return15m", "return1h",
        "return24h", "ratio15m", "ratio1h", "nativeRatio15m", "nativeRatio1h", "dayPosition"].includes(column) ? "desc" : "asc";
    }
  }

  function resetView() {
    minimum = 0;
    search = ""; venue = "all"; includeUnranked = false; favoritesOnly = false; minRatio = null;
    minDayPosition = null; maxDayPosition = null; sort = "server"; direction = "asc";
    preset = "standard"; lockedIds = null;
    selectedViewId = ""; viewName = "";
  }

  type Purpose = "market" | "movement" | "activity" | "favorites";
  const purposes: { id: Purpose; label: string }[] = [
    { id: "market", label: "市場全体" },
    { id: "movement", label: "短期の値動き" },
    { id: "activity", label: "売買代金の増加" },
    { id: "favorites", label: "お気に入り監視" }
  ];
  const activePurpose = $derived.by((): Purpose | null => {
    if (minimum !== 0 || search.trim() || includeUnranked || minRatio !== null ||
      minDayPosition !== null || maxDayPosition !== null || lockedIds || ratioPeriod !== "15m") return null;
    if (period === "24h" && order === "turnover" && sort === "server" &&
      direction === "asc" && preset === "standard") return favoritesOnly ? "favorites" : "market";
    if (!favoritesOnly && period === "15m" && preset === "movement") {
      if (order === "gainers" && sort === "server" && direction === "asc") return "movement";
      if (order === "turnover" && sort === (venue === "bitget" ? "nativeRatio15m" : "ratio15m") && direction === "desc") return "activity";
    }
    return null;
  });
  const purposeDescription = $derived(activePurpose === "market"
    ? `直近24時間の売買代金順で、${venue === "all" ? "市場全体" : `${venueLabel(venue)}取扱い銘柄`}を確認。`
    : activePurpose === "movement" ? "直近15分の上昇率順。15分・1時間・24時間の変化を並べて確認。"
    : activePurpose === "activity" && venue === "bitget" ? "Bitgetの15分売買代金を過去7日の同時刻と比べた普段比順。直前比と価格方向を併記。順位の数字は参照市場の全体順位です。"
    : activePurpose === "activity" ? "15分の売買代金の平常比順。過去24時間内の中央値と比較し、履歴不足は末尾に表示。順位は売買代金順です。"
    : activePurpose === "favorites" ? "お気に入りを直近24時間の売買代金順で確認。"
    : "表示条件を調整中。目的別の表示を選ぶと検索・追加条件・行順固定を解除します。");

  function applyPurpose(purpose: Purpose) {
    const currentVenue = venue;
    resetView();
    venue = currentVenue;
    ratioPeriod = "15m";
    period = purpose === "movement" || purpose === "activity" ? "15m" : "24h";
    order = purpose === "movement" ? "gainers" : "turnover";
    favoritesOnly = purpose === "favorites";
    preset = purpose === "movement" || purpose === "activity" ? "movement" : "standard";
    if (purpose === "activity") { sort = venue === "bitget" ? "nativeRatio15m" : "ratio15m"; direction = "desc"; }
  }

  function venueLabel(value: string) {
    return value === "bitget" ? "Bitget" : value === "hyperliquid" ? "Hyperliquid" : "Aster";
  }

  function referenceTarget(row: RankedRow): FavoriteTarget | null {
    if (!row.reference || row.mappingStatus !== "verified") return null;
    return {
      kind: "reference", id: row.id,
      referenceKey: `${row.reference.provider}:${row.reference.symbol}:${row.reference.revision}`,
      originals: row.originals.map((item) => `${item.instrumentId}:${item.versionId}`)
    };
  }

  function referenceFavoriteCurrent(row: RankedRow) {
    const target = referenceTarget(row);
    if (!target || target.kind !== "reference") return false;
    const saved = workspace?.favorites.find((entry) => entry.kind === "reference" && entry.id === row.id);
    return saved?.kind === "reference" && saved.referenceKey === target.referenceKey &&
      JSON.stringify([...saved.originals].sort()) === JSON.stringify([...target.originals].sort());
  }

  async function toggleFavorite(row: RankedRow) {
    const target = referenceTarget(row);
    if (!target) return;
    const key = favoriteKey(target);
    const current = favoriteIntent[key] ?? referenceFavoriteCurrent(row);
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

  async function saveCurrentView() {
    if (!workspace || !viewName.trim() || viewBusy) return;
    viewBusy = true;
    try {
      const response = await fetch("/api/user-workspace", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "saveView", id: selectedViewId || crypto.randomUUID(),
          name: viewName.trim(), expectedRevision: workspace.revision,
          view: {
            mode: "reference", period, order, reference, minimum, search, venue, favoritesOnly,
            includeUnranked, ratioPeriod, minRatio, minDayPosition, maxDayPosition,
            sort, direction, preset
          }
        })
      });
      if (!response.ok) throw new Error(response.status === 409
        ? "別の画面で表示設定が更新されました。再読込してください。" : "表示設定を保存できません");
      workspace = await response.json() as UserWorkspace;
      workspaceError = null;
    } catch (cause) {
      workspaceError = cause instanceof Error ? cause.message : "表示設定を保存できません";
    } finally { viewBusy = false; }
  }

  function applySavedView(id: string) {
    selectedViewId = id;
    const saved = workspace?.savedViews.find((item) => item.id === id);
    if (!saved || saved.view.mode !== "reference") return;
    const view = saved.view;
    try {
      rankingQuery(view.period as RankingPeriod, String(view.reference),
        view.order as RankingOrder, Number(view.minimum));
      period = view.period as RankingPeriod;
      order = view.order as RankingOrder;
      reference = String(view.reference);
      minimum = Number(view.minimum);
      search = typeof view.search === "string" ? view.search : "";
      venue = ["all", "bitget", "hyperliquid", "aster"].includes(String(view.venue))
        ? view.venue as typeof venue : "all";
      includeUnranked = view.includeUnranked === true;
      favoritesOnly = view.favoritesOnly === true;
      ratioPeriod = view.ratioPeriod === "1h" ? "1h" : "15m";
      minRatio = typeof view.minRatio === "number" ? view.minRatio : null;
      minDayPosition = typeof view.minDayPosition === "number" ? view.minDayPosition : null;
      maxDayPosition = typeof view.maxDayPosition === "number" ? view.maxDayPosition : null;
      sort = typeof view.sort === "string" ? view.sort as RankingSort : "server";
      direction = view.direction === "desc" ? "desc" : "asc";
      preset = view.preset === "movement" ? "movement" : "standard";
      lockedIds = null;
      viewName = saved.name;
      workspaceError = null;
    } catch { workspaceError = "保存した表示条件を適用できません"; }
  }

  async function removeSavedView() {
    if (!workspace || !selectedViewId || viewBusy) return;
    viewBusy = true;
    try {
      const response = await fetch("/api/user-workspace", {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action: "removeView", id: selectedViewId, expectedRevision: workspace.revision
        })
      });
      if (!response.ok) throw new Error(response.status === 409
        ? "別の画面で表示設定が更新されました。再読込してください。" : "表示設定を削除できません");
      workspace = await response.json() as UserWorkspace;
      selectedViewId = ""; viewName = ""; workspaceError = null;
    } catch (cause) {
      workspaceError = cause instanceof Error ? cause.message : "表示設定を削除できません";
    } finally { viewBusy = false; }
  }

  function moveSelected(offset: number) {
    const index = visibleRows.findIndex((row) => row.id === selectedId);
    const next = visibleRows[index + offset];
    if (next) void select(next);
  }

  function nativeHref(id: string, version: number) {
    const query = new URLSearchParams({
      mode: "native", instrument: id, version: String(version),
      returnPeriod: period, returnOrder: order,
      returnReference: reference, returnMinimum: String(minimum),
      returnSelected: selectedId ?? "", returnSearch: search, returnVenue: venue,
      returnIncludeUnranked: includeUnranked ? "1" : "0",
      returnFavoritesOnly: favoritesOnly ? "1" : "0",
      returnSort: sort, returnDirection: direction,
      returnRatioPeriod: ratioPeriod, returnMinRatio: minRatio === null ? "" : String(minRatio),
      returnMinDayPosition: minDayPosition === null ? "" : String(minDayPosition),
      returnMaxDayPosition: maxDayPosition === null ? "" : String(maxDayPosition),
      returnPreset: preset, returnListTop: String(listScroll.top), returnListLeft: String(listScroll.left),
      returnRestoreList: "1"
    });
    return `/?${query}`;
  }
</script>

<svelte:head><title>デイトレランキング | Prep Watchdeck</title></svelte:head>

<main class="ranking-page">
  {#if !query}<p class="notice" role="alert">売買代金の下限は0以上の数値を指定してください。</p>{/if}
  {#if error}<p class="notice" role="status">{error} <button type="button" onclick={() => query && refresh(query)}>再試行</button></p>{/if}
  {#if cachedSnapshot && loading}<p class="search-note" role="status">前回取得した一覧を表示しています。最新データを確認中です。</p>{/if}
  {#if stale}<p class="notice" role="status">更新が停止しています。表示値は {data ? rankingTimestamp(data.cutoff) : ""} JST 時点です。</p>{/if}
  {#if data}<RosterNotice {data} {now} />{/if}
  {#if workspaceError}<p class="notice" role="alert">{workspaceError}</p>{/if}

  <div class="workspace">
    <section class="ranking-list" class:mobile-hidden={mobileDetail} aria-labelledby="list-title">
  <div class="ranking-overview" class:mobile-hidden={mobileDetail}>
    <header class="topbar">
      <div><h1>ランキング</h1><p>取扱い銘柄を外部の参照契約で比較</p></div>
      <a class="reference-link" href="/settings">日次基準 · JST {reference}</a>
    </header>

    <div class="venue-switcher" role="group" aria-label="ランキングの取引所モード">
      <span>取扱い</span>
      <button type="button" aria-pressed={venue === "all"} onclick={() => venue = "all"}>すべて</button>
      <button type="button" aria-pressed={venue === "bitget"} onclick={() => venue = "bitget"}>Bitget</button>
      <button type="button" aria-pressed={venue === "hyperliquid"} onclick={() => venue = "hyperliquid"}>Hyperliquid</button>
    </div>

    <div class="purpose-switcher" role="group" aria-label="目的別の表示">
      {#each purposes as purpose}
        <button type="button" aria-pressed={activePurpose === purpose.id} onclick={() => applyPurpose(purpose.id)}>{purpose.label}</button>
      {/each}
    </div>
    <p class="purpose-description">{purposeDescription}
      {#if venue === "bitget" || venue === "hyperliquid"}<span>{venueLabel(venue)}の24時間売買代金を併記します。順位・騰落率・参照売買代金はBybit／Binanceのデータです。</span>{/if}
    </p>

    <section class="controls" aria-label="ランキングの表示">
      <label>比較期間<select aria-label="ランキングの比較期間" bind:value={period}>
        <option value="15m">15分</option><option value="1h">1時間</option>
        <option value="24h">直近24時間</option><option value="daily">JST基準時刻から</option>
      </select></label>
      <label>並び順<select aria-label="ランキングの並び順" bind:value={order}>
        <option value="gainers">上昇率</option><option value="losers">下落率</option><option value="turnover">売買代金</option>
      </select></label>
      <label class="search">銘柄検索<input aria-label="ランキングの銘柄検索" type="search" bind:value={search} placeholder="BTC、ETH、契約名" /></label>
      <label class="check"><input type="checkbox" bind:checked={favoritesOnly} />お気に入りのみ</label>
    </section>

    <div class="condition-summary" aria-label="適用中のランキング条件" aria-live="polite">
      <p><strong>{periodLabel} · {orderLabel}</strong> <span class="signal-conditions" title={venue === "bitget" ? `Bitgetの15分普段比${$preferences.surgeRatio}倍以上。価格方向の境界±${$preferences.directionPct}%` : `強調条件：昨日・一昨日の両方に対して${$preferences.surgeRatio}倍以上。方向の境界±${$preferences.directionPct}%`}> · 強調 ≥{$preferences.surgeRatio}倍 / ±{$preferences.directionPct}%</span>{#if activeConditions.length}<span> · {activeConditions.join(" · ")}</span>{/if}</p>
      {#if activeConditions.length}<button type="button" onclick={resetView}>条件をリセット</button>{/if}
    </div>

    <details class="ranking-conditions">
      <summary>ランキング条件{#if activeConditions.length}<span>{activeConditions.length} 項目適用中</span>{/if}</summary>
      <div class="advanced-controls">
        <label>売買代金の下限 · USDT<input aria-label="売買代金の下限" type="number" min="0" max="1000000000000000000" step="any" bind:value={minimum} /></label>
        <label>取扱い取引所<select aria-label="取扱い取引所" bind:value={venue}>
          <option value="all">すべて</option><option value="bitget">Bitget</option>
          <option value="hyperliquid">Hyperliquid</option><option value="aster">Aster</option>
        </select></label>
        <label>表示列<select aria-label="表示列プリセット" bind:value={preset}>
          <option value="standard">標準</option><option value="movement">値動き</option>
        </select></label>
        <label>参照の平常比期間<select aria-label="平常比期間" bind:value={ratioPeriod}>
          <option value="15m">15分</option><option value="1h">1時間</option>
        </select></label>
        <label>参照の平常比下限<input aria-label="平常比下限" type="number" min="0" step="any"
          value={minRatio ?? ""} oninput={(event) => minRatio = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <label>当日位置の下限 %<input aria-label="当日位置の下限" type="number" min="0" max="100" step="any"
          value={minDayPosition ?? ""} oninput={(event) => minDayPosition = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <label>当日位置の上限 %<input aria-label="当日位置の上限" type="number" min="0" max="100" step="any"
          value={maxDayPosition ?? ""} oninput={(event) => maxDayPosition = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <label class="check"><input type="checkbox" bind:checked={includeUnranked} />順位外・未対応も表示</label>
        <button type="button" onclick={() => lockedIds = lockedIds ? null : visibleRows.map((row) => row.id)}>
          {lockedIds ? "行順固定を解除" : "行順を固定"}
        </button>
        <button type="button" onclick={resetView}>条件をクリア</button>
      </div>
      <p class="search-note">検索と一覧の並べ替えは全体順位を変えません。比較期間・ランキングの並び順・売買代金下限は全対応銘柄に適用されます。</p>
    </details>

    <div class="saved-view-bar">
      <label>保存した表示<select aria-label="保存した表示" value={selectedViewId}
        onchange={(event) => applySavedView(event.currentTarget.value)}>
        <option value="">選択してください</option>
        {#each workspace?.savedViews.filter((item) => item.view.mode === "reference") ?? [] as saved}
          <option value={saved.id}>{saved.name}</option>
        {/each}
      </select></label>
      <details class="saved-view-management">
        <summary>表示条件を保存／管理</summary>
        <div class="view-actions">
          <label>表示名<input aria-label="表示名" maxlength="80" bind:value={viewName} /></label>
          <button type="button" disabled={viewBusy || !viewName.trim() || !workspace} onclick={saveCurrentView}>表示条件を保存</button>
          <button type="button" disabled={viewBusy || !selectedViewId} onclick={removeSavedView}>保存した表示を削除</button>
        </div>
      </details>
    </div>
    <div class="comparison-status" aria-live="polite">
      {#if data}
        <span>比較 · JST {rankingTimestamp(data.anchor)} → {rankingTimestamp(data.cutoff)}</span>
        <span>対象 {data.coverage.cryptoRows} · 参照対応 {data.coverage.supported} · 比較可能 {data.coverage.valid}</span>
        <span>
          {visibleRows.length} 件表示 / {data.coverage.ranked} 件の全体順位
        </span>
        <span class="refresh-state">{loading ? "更新中" : stale ? "更新停止" : "毎分更新"}</span>
      {:else}<p>{loading ? "全対象のランキングを読み込んでいます" : "ランキングはまだ利用できません"}</p>{/if}
    </div>
  </div>

      {#if venue !== "bitget" && volumeSpotlight.length}
        <div class="volume-spotlight" role="group" aria-label={`${periodLabel}・昨日と一昨日の両方に対して売買代金が${$preferences.surgeRatio}倍以上の銘柄`} data-testid="volume-spotlight">
          {#each volumeSpotlight as row (row.id)}
            <RelativeVolumeSignal {row} decimals={turnoverDecimals} showAsset isNew={newVolumeVisible && newVolumeRows.has(row.id)} onselect={() => select(row)} />
          {/each}
        </div>
      {/if}
      <div class="list-heading"><h2 id="list-title">{order === "gainers" ? "上昇率" : order === "losers" ? "下落率" : "売買代金"}ランキング</h2><span>{visibleRows.length} 件</span></div>
      {#if addedRows}<p class="search-note">新しい行が {addedRows} 件あります。固定解除で表示します。</p>{/if}
      <div class="table-scroll" aria-busy={loading} bind:this={tableScroll}
        onscroll={() => { if (!mobileDetail) listScroll = { top: tableScroll.scrollTop, left: tableScroll.scrollLeft }; }}>
        <table>
          <thead><tr>
            <th scope="col" class="desktop-only">保存</th>
            <th scope="col"><span class="desktop-only">全体</span>順位</th>
            <th scope="col" aria-sort={sort === "asset" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("asset")}>銘柄<span class="desktop-only"> / 取扱い</span></button></th>
            <th scope="col" class="desktop-only" aria-sort={sort === "referenceClose" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("referenceClose")}>参照終値</button></th>
            <th scope="col" class:ranking-basis={order !== "turnover"} aria-sort={sort === "returnPct" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("returnPct")}>騰落率</button></th>
            {#if preset === "movement"}<th scope="col" class="desktop-only">15分 / 1時間 / 24時間</th>{/if}
            <th scope="col" class:ranking-basis={order === "turnover"} aria-sort={sort === "quoteTurnover" || sort === "nativeRatio15m" || sort === "nativeRatio1h" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("quoteTurnover")}>売買代金<span class="turnover-unit"> · USDT</span></button>
              {#if venue === "bitget"}<span class="native-sort-controls">普段比 <button type="button" aria-label="Bitget 15分普段比で並べ替え" aria-pressed={sort === "nativeRatio15m"} onclick={() => chooseSort("nativeRatio15m")}>15m</button><button type="button" aria-label="Bitget 1時間普段比で並べ替え" aria-pressed={sort === "nativeRatio1h"} onclick={() => chooseSort("nativeRatio1h")}>1h</button></span>{/if}
            </th>
          </tr></thead>
          <tbody>
            {#each visibleRows.slice(0, limit) as row (row.id)}
              {@const activityView = nativeViews.get(row.id) ?? { row: null, reason: "短時間データなし" }}
              {@const volumeSignal = venue === "bitget" ? { kind: nativeActivityKind(activityView.row, $preferences) } : relativeVolumeState(row, stale, $preferences)}
              <tr class:selected={selectedId === row.id} class:volume-surge={volumeSignal.kind !== null}
                class:surge-up={volumeSignal.kind === "up"} class:surge-down={volumeSignal.kind === "down"}
                data-testid="ranking-row" data-asset={row.asset} data-volume-surge={volumeSignal.kind ?? ""}>
                <td class="desktop-only"><button type="button" disabled={!referenceTarget(row)}
                  title={workspace?.favorites.some((entry) => entry.kind === "reference" && entry.id === row.id) && !referenceFavoriteCurrent(row)
                    ? "参照対応が変わりました。確認してから再登録してください" : undefined}
                  aria-label={`${row.asset}をお気に入り${(favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)) ? "解除" : "登録"}`}
                  aria-pressed={favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)}
                  onclick={() => toggleFavorite(row)}>★</button></td>
                <td class="rank">{row.rank ?? "—"}{#if sort === "server"}
                  {@const changeLabel = rankChangeLabel(row, comparisonExpired)}
                  <small class="rank-change" data-testid="rank-change" aria-label={changeLabel} title={changeLabel}>
                    {(changeLabel.startsWith("比較不可") || row.rank === null) ? "—" : changeLabel}
                  </small>
                {/if}</td>
                <th scope="row" class="asset-cell"><button type="button" class="select-row" aria-pressed={selectedId === row.id} onclick={() => select(row)}>
                  <div class="asset-icon-slot"><AssetIcon symbol={row.asset} assetId={row.id} originals={row.originals} /></div>
                  <strong>{row.asset}</strong><span>{row.venues.map((v) => v === "hyperliquid" ? "Hyperliquid" : v === "bitget" ? "Bitget" : "Aster").join(" · ")}</span>
                  <small class="desktop-only">{referenceLabel(row)}</small>
                  <small class="mobile-only">{row.reference ? `参照 ${row.reference.provider === "bybit" ? "Bybit" : "Binance"}` : "参照未対応"}</small>
                </button>
                  <button class="mobile-only mobile-favorite" type="button" disabled={!referenceTarget(row)}
                    title={workspace?.favorites.some((entry) => entry.kind === "reference" && entry.id === row.id) && !referenceFavoriteCurrent(row)
                      ? "参照対応が変わりました。確認してから再登録してください" : undefined}
                    aria-label={`${row.asset}をお気に入り${(favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)) ? "解除" : "登録"}`}
                    aria-pressed={favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)}
                    onclick={() => toggleFavorite(row)}>★</button>
                  {#if mobileSortBasis(row)}<small class="mobile-only mobile-sort-basis">{mobileSortBasis(row)}</small>{/if}
                  {#if preset === "movement"}<small class="mobile-only mobile-movement">{#each ["15m", "1h", "24h"] as window}
                    <span>{window}: {row.windows[window as "15m" | "1h" | "24h"].returnPct === null ? "未取得" : formatPriceChange(row.windows[window as "15m" | "1h" | "24h"].returnPct!)}</span>
                  {/each}</small>{/if}
                </th>
                <td class="numeric desktop-only">{row.referenceClose.status === "ready" ? formatPrice(row.referenceClose.value) : "未取得"}</td>
                <td class="numeric change" class:ranking-basis={order !== "turnover"} class:up={(row.returnPct ?? 0) > 0} class:down={(row.returnPct ?? 0) < 0}>
                  {#if row.returnPct !== null}{formatPriceChange(row.returnPct)}{:else}<span class="missing">{rankingRowStateLabel(row)}</span>{/if}
                  <small class="indicator" data-testid="day-position">当日位置 <span class:missing={row.dayRangePosition.status !== "ready"}>{indicatorLabel(row.dayRangePosition, "%")}</span></small>
                </td>
                {#if preset === "movement"}
                  <td class="numeric desktop-only">{#each ["15m", "1h", "24h"] as window}
                    <span>{window}: {row.windows[window as "15m" | "1h" | "24h"].returnPct === null
                      ? "未取得" : formatPriceChange(row.windows[window as "15m" | "1h" | "24h"].returnPct!)}</span>
                  {/each}</td>
                {/if}
                <td class="numeric turnover" class:ranking-basis={order === "turnover"}>{#if row.quoteTurnover !== null}<span title={`${formatTurnover(row.quoteTurnover, turnoverDecimals)} USDT`}>{turnoverLabel(row.quoteTurnover, turnoverDecimals, $preferences.turnoverNotation === "compact")}</span>{:else}<span class="missing">未取得</span>{/if}
                  {#if venue === "bitget" || venue === "hyperliquid"}
                    {@const native = venueTurnover(venue, row, nativeUniverse, now)}
                    <div class="native-turnover" data-testid={`${venue}-turnover`}
                      title={native.reason ?? `${formatTurnover(native.value, turnoverDecimals)} ${native.unit} · 取得 ${rankingTimestamp(Date.parse(native.observedAt!))} JST`}>
                      <small>{venueLabel(venue)} 24h</small>
                      <span class:missing={native.value === null}>{formatVenueTurnover(native.value, turnoverDecimals)}{native.value !== null ? ` ${native.unit}` : ""}</span>
                    </div>
                  {/if}
                  <span class="volume-signal-slot">
                    {#if venue === "bitget"}
                      <NativeActivitySignal row={activityView.row} reason={activityView.reason} decimals={turnoverDecimals} onselect={() => select(row)} />
                    {:else}
                      <RelativeVolumeSignal {row} expired={stale} decimals={turnoverDecimals}
                        isNew={newVolumeVisible && newVolumeRows.has(row.id)} onselect={() => select(row)} />
                    {/if}
                  </span>
                  {#if row.rank === null && row.returnPct !== null}<small>{rankingStateLabel(row.state)}</small>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if !loading && visibleRows.length === 0}<p class="empty">この条件の銘柄はありません。順位外・未対応の表示でも状態を確認できます。</p>{/if}
      </div>
      {#if visibleRows.length > limit}<button class="more" type="button" onclick={() => limit += 50}>さらに50件を表示（{limit} / {visibleRows.length}）</button>{/if}
      <details class="metric-help"><summary>指標の読み方</summary>
        <p class="metric-note">取扱いはBitget / Hyperliquid / Asterの元契約です。参照取引所の契約で騰落率・売買代金を比較し、取扱い取引所の合計にはしません。</p>
        <p class="metric-note">売買代金は同じ比較期間における、参照取引所の当該契約のUSDT建て合計です。3取引所や市場全体の合計ではありません。</p>
        <p class="metric-note">「Bitget 24h」「Hyperliquid 24h」は、各取引所が配信する直近24時間の売買代金です。単位は契約ごとのUSDT／USDCを表示します。比較期間を変えても24時間値です。kは千、mは百万を表します。取得できない値・古い値・契約版が一致しない値は「—」にします。</p>
        <p class="metric-note">Bitgetの短時間表示は、15分・1時間の売買代金の普段比と直前比、15分の価格変化、直近4区間の推移です。約3分前までの確定1分足を1分ごとに集計します。普段比は過去7日の同時刻・同じ長さの窓の中央値が基準で、3日以上の完全な履歴が必要です。棒の欠測と実測ゼロは区別します。Hyperliquidの短時間指標は表示しません。</p>
        <p class="metric-note">全体順位は全対応銘柄から計算します。検索やお気に入りは表示する行だけを絞ります。列見出しによる並べ替え後も全体順位は維持します。</p>
        <p class="metric-note">順位変化は同じ条件での1分前の順位 − 現順位です。+は順位上昇、−は順位低下、0は同順位。「新規」は前回だけ順位外だった銘柄です。スマホの順位変化の「—」は比較できない状態で、理由は銘柄詳細で確認できます。</p>
        <p class="metric-note">売買代金の平常比は、直近24時間内の同期間中央値との比較です（最新窓を除く15分95窓・1時間23窓）。当日位置はJST 00:00からの高安に対する終値の位置で、0%が安値、100%が高値です。</p>
        <p class="metric-note">Bitget以外のモードの売買代金の棒は左から一昨日・昨日・現在で、同じ銘柄・参照契約の同じ時間帯を比較します。両日比{$preferences.surgeRatio}倍以上は青く強調し、矢印は騰落率が+{$preferences.directionPct}%以上／−{$preferences.directionPct}%以下の方向、それ以外は横線です。小さな点は連続した世代で新しく条件を満たした銘柄です。履歴不足・比較元ゼロは「?」、更新停止は時計で示します。ホバーまたは選択で比較値と理由を確認できます。過去24時間の平常比は銘柄詳細にも表示します。</p>
        <p class="metric-note">スマホでは参照終値・追加指標・出典を銘柄詳細で確認できます。騰落率の計算基準は設定の「騰落率の基準時刻（JST）」で変更します。</p>
      </details>
      {#if data}
        <details class="coverage"><summary>対応範囲と除外理由</summary>
          <p>元の {data.coverage.sourceInstruments} 契約を {data.coverage.rows} 行に整理。Widget対応 {data.coverage.widgetSupported} 銘柄。</p>
          <p>対象 {data.coverage.cryptoRows} / 参照対応 {data.coverage.supported} / 比較可能 {data.coverage.valid} 銘柄。</p>
          <p>元契約の数量換算が未確認: {quantityUnverified} 契約。Chart対応が未確認: {widgetReview} 銘柄。各確認状態はランキングの参照対応と別に管理します。</p>
          <dl>{#each Object.entries(data.coverage.reasons) as [state, count]}<div><dt>{rankingStateLabel(state as RankedRow["state"]) ?? state}</dt><dd>{count}</dd></div>{/each}</dl>
          <p>名簿確認: {rankingTimestamp(data.rosterGeneratedAt)} JST</p>
        </details>
      {/if}
    </section>

    <section class="chart-section" class:mobile-hidden={!mobileDetail} aria-labelledby="chart-title">
      <button class="mobile-only detail-back" type="button" bind:this={detailBack} onclick={() => window.history.back()}>一覧へ戻る</button>
      {#if selected}
        <div class="selected-heading">
          <div><span>選択中の参照契約</span><h2 id="chart-title">
            <AssetIcon symbol={selected.asset} assetId={selected.id} originals={selected.originals} size={32} />
            <span>{selected.asset}</span>
          </h2></div>
          <p class="comparison-time">{#if data}比較値 · JST {rankingTimestamp(data.cutoff)}<br />{stale ? "更新停止・過去時点の値" : "確定1分足で比較"}{:else}比較条件を取得中{/if}</p>
        </div>
        <section class="source-context" aria-label="参照市場と確認する取引所">
          <div class="reference-source"><span>ランキング・チャートの参照</span><strong>{referenceLabel(selected)}</strong><small>この参照契約の価格・売買代金です。</small></div>
          <div class="native-source"><span>確認する取引所</span>
            <div class="native-candidates" aria-label="現在の取扱い契約">
              {#if !selectedRemoved}
                {#if nativeLoading && !nativeUniverse}<p role="status">現在の取扱い契約を確認しています。</p>
                {:else if nativeError}<p role="status">{nativeError}</p>
                {:else if !nativeUniverseFresh(nativeUniverse, now)}<p role="status">取扱い情報が期限切れです。更新後に再確認します。</p>
                {:else}
                {#each nativeCandidates as instrument (instrument.venueInstrumentId)}
                  <a href={nativeHref(instrument.venueInstrumentId, instrument.venueInstrumentVersionId)}>{venueLabel(instrument.venue)} · {instrument.sourceSymbol} を確認</a>
                {:else}<p>現在の取扱い情報で、同一契約として確認できる移動先がありません。</p>{/each}
                {/if}
              {:else}<p>対応表から削除されたため、取引所別への移動を停止しています。</p>{/if}
            </div>
          </div>
        </section>
        <div class="native-candidates">
          <button type="button" onclick={() => moveSelected(-1)} disabled={visibleRows.findIndex((row) => row.id === selectedId) <= 0}>前の銘柄</button>
          <button type="button" onclick={() => moveSelected(1)} disabled={visibleRows.findIndex((row) => row.id === selectedId) >= visibleRows.length - 1}>次の銘柄</button>
        </div>
        {#if data && !selectedRemoved}
          <dl class="selected-metrics primary-metrics" data-testid="selected-primary-metrics">
            <div><dt>参照終値 · USDT</dt><dd>{selected.referenceClose.status === "ready" ? formatPrice(selected.referenceClose.value) : "未取得"}</dd></div>
            <div><dt>騰落率 · {periodLabel === "15分" || periodLabel === "1時間" ? `直近${periodLabel}` : periodLabel}</dt><dd class:up={(selected.returnPct ?? 0) > 0} class:down={(selected.returnPct ?? 0) < 0}>{selected.returnPct !== null ? formatPriceChange(selected.returnPct) : rankingRowStateLabel(selected)}</dd></div>
            <div><dt>売買代金 · USDT</dt><dd>{selected.quoteTurnover !== null ? formatTurnover(selected.quoteTurnover, turnoverDecimals) : "未取得"}</dd></div>
            {#if venue === "bitget" || venue === "hyperliquid"}
              {@const native = venueTurnover(venue, selected, nativeUniverse, now)}
              <div><dt>{venueLabel(venue)} 24h{native.unit ? ` · ${native.unit}` : ""}</dt><dd>{formatVenueTurnover(native.value, turnoverDecimals)}</dd></div>
              <div class="native-turnover-status"><dt>{venueLabel(venue)}取得状態</dt><dd>{native.reason ?? `${rankingTimestamp(Date.parse(native.observedAt!))} JST`}</dd></div>
            {/if}
          </dl>
          {#if venue === "bitget"}
            {@const activityView = nativeActivity(selected, activityData, now)}
            <NativeActivityDetails row={activityView.row} reason={activityView.reason} decimals={turnoverDecimals} />
          {:else}<RelativeVolumeDetails row={selected} expired={stale} decimals={turnoverDecimals} />{/if}
        {/if}
        {#if selected.state === "mapping_review"}<p class="selection-notice">{rankingRowStateLabel(selected)}。確認できるまで順位とチャートに含めません。</p>
        {:else if selected.state === "unsupported"}<p class="selection-notice">{rankingRowStateLabel(selected)}。順位とチャートの対象外です。</p>{/if}
        {#if selected.originals.some((item) => item.multiplier === null)}
          <p class="selection-notice" data-testid="quantity-review">元の取引所の数量換算は未確認です。{#if selected.mappingStatus === "verified"}ランキングの数値は、確認済みの参照契約から計算しています。{/if}元契約への数量・価格の換算には利用できません。</p>
        {/if}
        {#if selectedRemoved}<p class="selection-notice">選択銘柄は更新後の対応表にありません。選択名を維持し、チャートを停止しています。</p>
        {:else if selectedFiltered}<p class="selection-notice">選択銘柄は現在の一覧条件の対象外です。選択は維持しています。</p>{/if}
        {#if symbol}<ReferenceChart {symbol} bind:interval />{:else}<div class="chart-empty"><h3>この参照契約のWidgetは利用できません</h3><p>{selected.widget.status === "review" ? "チャートの対応確認が必要です。" : "対応するチャートが確認できません。"}</p>{#if selected.mappingStatus === "verified"}<p>Chartの対応状況は、ランキングの数値計算には影響しません。</p>{/if}</div>{/if}
        {#if data && !selectedRemoved}
          <dl class="selected-metrics" data-testid="selected-metrics">
            <div><dt>1分前からの順位変化</dt><dd>{rankChangeLabel(selected, comparisonExpired)}</dd></div>
            <div><dt>売買代金の平常比</dt><dd>{indicatorLabel(selected.turnoverRatio, "倍")}</dd></div>
            <div><dt>JST当日の高安位置 · 00:00から</dt><dd>{indicatorLabel(selected.dayRangePosition, "%")}</dd></div>
            {#each ["15m", "1h", "24h"] as window}<div><dt>{window === "15m" ? "15分" : window === "1h" ? "1時間" : "24時間"}騰落率</dt><dd>{selected.windows[window as "15m" | "1h" | "24h"].returnPct === null ? "未取得" : formatPriceChange(selected.windows[window as "15m" | "1h" | "24h"].returnPct!)}</dd></div>{/each}
          </dl>
        {/if}
        {#if noteTarget && selected.reference && data && !selectedRemoved}
          <details>
            <summary>この参照市場の観測メモ</summary>
            <label>保存先の取扱い契約<select value={noteTarget.venueInstrumentId} onchange={event => noteTargetId = event.currentTarget.value}>
              {#each nativeCandidates as instrument}<option value={instrument.venueInstrumentId}>{instrument.venueInstrumentId}</option>{/each}
            </select></label>
            <MarketPastNotesPanel venueInstrumentId={noteTarget.venueInstrumentId}
              venueInstrumentVersionId={noteTarget.venueInstrumentVersionId}
              referenceContext={{ generationId: data.generationId, observation: {
                source: selected.reference.provider, symbol: selected.reference.symbol,
                revision: selected.reference.revision, cutoff: new Date(data.cutoff).toISOString(),
                period: data.period, dailyReferenceJst: data.dailyReferenceJst, stale,
                returnPct: selected.returnPct, quoteTurnover: selected.quoteTurnover,
                close: selected.referenceClose.value, turnoverRatio: selected.turnoverRatio.value,
                dayPosition: selected.dayRangePosition.value
              } }} />
          </details>
        {/if}
        {#if storageMessage}<p class="selection-notice" role="status">{storageMessage}</p>{/if}
        <details class="contracts"><summary>元の取扱い契約と数量単位</summary>
          {#each selected.originals as item}<p><strong>{item.venue}</strong> · {item.symbol} {#if item.multiplier !== null}· 1単位 = {item.multiplier.toLocaleString("en-US")} {selected.asset}{:else}· 数量単位は要確認{/if}</p>{/each}
          {#if selected.reference}<p>参照契約: 1単位 = {selected.reference.multiplier.toLocaleString("en-US")} {selected.asset}。価格・売買代金はUSDT建て。</p>{/if}
        </details>
      {:else}<div class="chart-empty"><span>参照チャート</span><h2 id="chart-title">銘柄を選んで確認</h2><p>一覧の銘柄名を選ぶと、同じ参照契約のTradingViewチャートを表示します。</p><p>チャートの時間足は、ランキングの比較期間とは別に設定できます。</p></div>{/if}
    </section>
  </div>
</main>

<style>
  .ranking-page { padding: var(--space-page); color: var(--text); max-width: 1900px; margin: 0 auto; }
  .venue-switcher { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs); padding-top: var(--space-sm); }
  .venue-switcher > span { color: var(--muted); font-size: var(--type-label-caps-size); margin-right: var(--space-xs); }
  .venue-switcher button { font-weight: 700; }
  .purpose-switcher { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-xs); padding-top: var(--space-md); }
  .purpose-switcher button { min-height: var(--control-height-touch); padding: var(--space-xs); font-weight: 700; }
  .ranking-page :is(.purpose-switcher, .venue-switcher) button[aria-pressed="true"] { color: var(--focus-on); background: var(--focus); border-color: var(--focus); }
  .purpose-description { margin: var(--space-xs) 0 var(--space-sm); color: var(--muted); font-size: var(--type-label-caps-size); line-height: 1.5; }
  .source-context { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: var(--space-md); padding: var(--space-md) 0; border-bottom: 1px solid var(--line); }
  .source-context > div { min-width: 0; }
  .source-context span, .source-context small { display: block; color: var(--muted); font-size: var(--type-label-caps-size); line-height: 1.5; }
  .reference-source strong { display: block; margin: var(--space-xs) 0; font-size: var(--type-data-md-size); overflow-wrap: anywhere; }
  .native-source .native-candidates { padding: var(--space-xs) 0 0; gap: var(--space-xs); }
  .native-source .native-candidates a { min-height: var(--control-height-dense); box-sizing: border-box; padding: var(--space-xs) var(--space-sm); text-underline-offset: 3px; }
  .native-source .native-candidates p { margin: 0; line-height: 1.5; }
  .primary-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-md); padding: var(--space-md) 0; margin: 0; border-bottom: 1px solid var(--line); }
  .selected-metrics.primary-metrics > div { display: block; min-width: 0; }
  .primary-metrics dt { color: var(--muted); font-size: var(--type-label-caps-size); }
  .selected-metrics.primary-metrics dd { font-size: var(--type-data-lg-size); line-height: 1.4; margin-top: var(--space-xs); }
  .ranking-page :where(a, button, input, select, summary):focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
  .signal-conditions { font-size: var(--type-label-caps-size); color: var(--muted); }
  .topbar { display: flex; justify-content: space-between; align-items: center; gap: var(--space-md); padding: 0 0 var(--space-sm); border-bottom: 1px solid var(--line-strong); }
  h1 { margin: 0; font-size: var(--type-title-lg-size); line-height: var(--type-title-lg-leading); }
  .topbar p, .metric-note, .search-note { margin: var(--space-xs) 0; color: var(--muted); font-size: var(--type-body-sm-size); line-height: 1.5; }
  .reference-link { color: var(--muted); font-size: var(--type-label-caps-size); text-underline-offset: 3px; white-space: nowrap; }
  .controls { display: grid; grid-template-columns: 140px 140px minmax(180px, 1fr) auto; align-items: end; gap: var(--space-md); padding: var(--space-sm) 0; }
  label { display: grid; gap: var(--space-xs); color: var(--muted); font-size: var(--type-label-caps-size); min-width: 0; }
  input, select, button { box-sizing: border-box; min-width: 0; min-height: var(--control-height-dense); border: 1px solid var(--line-strong); border-radius: 0; background: var(--surface); color: var(--text); padding: 0 var(--space-sm); font: inherit; font-size: var(--type-body-sm-size); }
  button { cursor: pointer; }button:disabled { cursor: default; opacity: .55; }
  .check { display: flex; align-items: center; min-height: var(--control-height-dense); white-space: nowrap; cursor: pointer; }
  .check input { min-height: 0; accent-color: var(--focus); }
  .condition-summary { display: flex; gap: var(--space-sm); justify-content: space-between; align-items: center; min-height: 28px; font-size: var(--type-body-sm-size); }
  .condition-summary p { margin: var(--space-xs) 0; min-width: 0; overflow-wrap: anywhere; line-height: 1.5; }
  .condition-summary span { color: var(--muted); }.condition-summary button { flex-shrink: 0; }
  .ranking-conditions { border-block: 1px solid var(--line); }
  summary { cursor: pointer; min-height: var(--control-height-dense); display: list-item; align-content: center; font-size: var(--type-body-sm-size); color: var(--subtle); }
  .ranking-conditions summary > span { margin-left: var(--space-md); color: var(--muted); font-size: var(--type-label-caps-size); }
  .advanced-controls { display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); align-items: end; gap: var(--space-md); padding: var(--space-sm) 0; }
  .saved-view-bar { display: grid; grid-template-columns: minmax(180px, 280px) minmax(180px, 1fr); gap: var(--space-md); align-items: end; padding: var(--space-sm) 0; }
  .saved-view-management[open] { grid-column: 1 / -1; }
  .view-actions { display: flex; flex-wrap: wrap; gap: var(--space-sm); align-items: end; padding: var(--space-sm) 0; }.view-actions label { flex: 1; min-width: 160px; }
  .notice { margin: var(--space-sm) 0; padding: var(--space-sm) var(--space-md); border-left: 3px solid var(--warning-border); background: var(--surface); color: var(--warning); font-size: var(--type-body-sm-size); line-height: 1.5; }
  .comparison-status { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs) var(--space-md); background: var(--panel-strong); padding: var(--space-sm); border-block: 1px solid var(--line); color: var(--muted); font-size: var(--type-label-caps-size); font-variant-numeric: tabular-nums; line-height: 1.5; }
  .comparison-status p { margin: 0; }.refresh-state { margin-left: auto; }
  .metric-note { margin: var(--space-sm) 0; font-size: var(--type-label-caps-size); }
  .workspace { display: grid; grid-template-columns: minmax(470px, .95fr) minmax(0, 1.05fr); gap: var(--space-lg); align-items: start; }
  .ranking-list, .chart-section { min-width: 0; }
  .list-heading { display: flex; justify-content: space-between; align-items: center; padding: var(--space-sm) 0; }
  .list-heading h2 { margin: 0; font-size: var(--type-heading-md-size); }
  .list-heading > span { font-size: var(--type-body-sm-size); color: var(--muted); }
  .search-note { font-size: var(--type-label-caps-size); }
  .table-scroll { max-height: 640px; overflow: auto; border-block: 1px solid var(--line-strong); }
  table { border-collapse: collapse; width: 100%; font-size: var(--type-body-sm-size); }
  th, td { padding: var(--space-sm); border-bottom: 1px solid var(--line); vertical-align: middle; }
  thead th { position: sticky; top: 0; z-index: 1; background: var(--panel-strong); color: var(--muted); font-size: var(--type-label-caps-size); font-weight: 500; text-align: right; white-space: nowrap; }
  thead th:nth-child(2), thead th:nth-child(3) { text-align: left; }
  thead button { font-size: inherit; color: inherit; padding: 0; background: transparent; border: 0; }
  tbody th { font-weight: 500; text-align: left; }
  tr { background: var(--panel); }
  tr.volume-surge:not(.selected) { background: color-mix(in srgb, var(--activity) 7%, var(--panel-solid)); box-shadow: inset 3px 0 var(--activity); }
  tr.surge-up:not(.selected) { box-shadow: inset 3px 0 var(--up); }
  tr.surge-down:not(.selected) { box-shadow: inset 3px 0 var(--down); }
  tr.selected { background: var(--panel-selected); box-shadow: inset 3px 0 var(--focus); }
  button[aria-pressed="true"]:not(.select-row) { color: var(--focus); }
  .rank { color: var(--muted); font-variant-numeric: tabular-nums; width: 38px; text-align: right; }
  .rank-change { display: block; font-size: var(--type-label-caps-size); white-space: normal; overflow-wrap: anywhere; min-width: 40px; }
  .ranking-basis { font-weight: 750; }.ranking-basis > button { color: var(--text); }
  .selected-metrics { color: var(--subtle); font-size: var(--type-body-sm-size); line-height: 1.6; }
  .selected-metrics div { display: flex; justify-content: space-between; flex-wrap: wrap; gap: var(--space-xs); }
  .selected-metrics dd { margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .primary-metrics dd { font-weight: 750; }
  .indicator { display: block; color: var(--muted); font-size: var(--type-label-caps-size); white-space: normal; }
  .select-row { display: grid; grid-template-columns: 22px minmax(0, 1fr); width: 100%; gap: var(--space-xxs) var(--space-sm); border: 0; padding: 0; background: transparent; color: var(--text); text-align: left; min-height: 42px; }
  .asset-icon-slot { grid-column: 1; grid-row: 1 / span 3; align-self: center; }
  .select-row > strong, .select-row > span, .select-row > small { grid-column: 2; min-width: 0; }
  .select-row strong { font-size: var(--type-data-md-size); overflow-wrap: anywhere; }
  .select-row span, .select-row small { color: var(--muted); font-size: var(--type-label-caps-size); overflow-wrap: anywhere; }
  .numeric { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
  .up { color: var(--up); }.down { color: var(--down); }
  .missing { color: var(--quality-risk); font-size: var(--type-label-caps-size); white-space: normal; }
  .turnover small { display: block; color: var(--muted); font-size: var(--type-label-caps-size); white-space: normal; }
  .native-sort-controls { display: flex; align-items: center; justify-content: flex-end; gap: 4px; color: var(--muted); font-size: var(--type-label-caps-size); white-space: nowrap; }
  .native-sort-controls button { flex: 0 0 auto; width: auto; min-height: 24px; min-width: 24px; padding: 0 2px; }
  .volume-signal-slot { display: block; }
  .native-turnover { margin-top: var(--space-xs); border-top: 1px solid var(--line); padding-top: var(--space-xxs); font-weight: 500; }
  .native-turnover-status { color: var(--muted); font-size: var(--type-label-caps-size); }
  .volume-spotlight { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 140px), 1fr)); gap: var(--space-xs); margin-top: var(--space-sm); }
  @media (max-width: 960px) {
    .volume-spotlight { grid-template-columns: none; grid-auto-flow: column; grid-auto-columns: 148px; overflow-x: auto; overscroll-behavior-x: contain; }
  }
  .more { width: 100%; min-height: 44px; }
  .empty { padding: var(--space-lg); color: var(--muted); line-height: 1.6; font-size: var(--type-body-sm-size); }
  .coverage, .contracts, .metric-help { border-bottom: 1px solid var(--line); padding: var(--space-xs) 0; font-size: var(--type-body-sm-size); color: var(--muted); }
  .coverage dl { display: grid; gap: var(--space-xs); }.coverage dl div { display: flex; justify-content: space-between; }.coverage dd { font-variant-numeric: tabular-nums; }
  .chart-section { position: sticky; top: var(--space-sm); }
  .selected-heading { border-bottom: 1px solid var(--line-strong); padding: var(--space-sm) 0; }
  .selected-heading { display: flex; justify-content: space-between; gap: var(--space-md); align-items: center; }
  .selected-heading > div > span { color: var(--muted); font-size: var(--type-label-caps-size); }
  .selected-heading h2 { display: flex; align-items: center; gap: var(--space-sm); margin: var(--space-xs) 0; font-size: var(--type-title-lg-size); }
  .selected-heading h2 > span { min-width: 0; overflow-wrap: anywhere; }
  .selected-heading .comparison-time { text-align: right; font-variant-numeric: tabular-nums; flex-shrink: 0; }
  .selected-heading p { margin: var(--space-xs) 0; color: var(--subtle); font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
  .native-candidates { display: flex; flex-wrap: wrap; gap: var(--space-sm); padding: var(--space-sm) 0; }
  .native-candidates a { display: flex; align-items: center; color: var(--focus); border: 1px solid var(--line-strong); padding: var(--space-sm); font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
  .native-candidates p { font-size: var(--type-body-sm-size); color: var(--muted); }
  .selection-notice { border-left: 2px solid var(--warning-border); padding: var(--space-sm); color: var(--warning); font-size: var(--type-body-sm-size); line-height: 1.5; }
  .chart-empty { display: flex; flex-direction: column; justify-content: center; min-height: 320px; padding: var(--space-xl); border: 1px solid var(--line); background: var(--panel); }
  .chart-empty > span, .chart-empty p { color: var(--muted); font-size: var(--type-body-sm-size); line-height: 1.7; }.chart-empty h2, .chart-empty h3 { font-size: var(--type-heading-md-size); }
  .mobile-only { display: none; }
  @media (min-width: 961px) and (max-width: 1300px) {
    .controls, .advanced-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .purpose-switcher { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 960px) {
    .purpose-switcher { grid-template-columns: repeat(2, minmax(0, 1fr)); padding-top: var(--space-sm); }
    .source-context { grid-template-columns: minmax(0, 1fr); gap: var(--space-sm); }
    .native-source .native-candidates a { min-height: var(--control-height-touch); }
    .primary-metrics { gap: var(--space-sm); }
    .selected-metrics.primary-metrics dd { font-size: var(--type-data-md-size); }
    .selected-heading .comparison-time { font-size: var(--type-label-caps-size); }

    .workspace { grid-template-columns: minmax(0, 1fr); gap: 0; }.chart-section { position: static; }
    .mobile-hidden, .desktop-only { display: none; }
    .mobile-only { display: block; }
    .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-sm); }.table-scroll { max-height: 60vh; }
    input, select, button, summary { min-height: var(--control-height-touch); }.check { min-height: 44px; }
    .check input { min-height: 0; }
    .advanced-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .topbar p { display: none; }.topbar { min-height: 44px; padding-bottom: var(--space-xs); }h1 { font-size: 22px; }
    .reference-link { display: flex; align-items: center; min-height: 44px; }
    .comparison-status { gap: var(--space-xs) var(--space-sm); }.comparison-status > span:first-child { flex-basis: 100%; }
    .condition-summary { font-size: var(--type-label-caps-size); }
    .saved-view-bar { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-sm); }
    .view-actions { display: grid; grid-template-columns: minmax(0, 1fr); }.view-actions label { min-width: 0; }
    table { table-layout: fixed; }
    th, td { padding: var(--space-sm) var(--space-xs); }
    thead th { font-size: 10px; white-space: normal; }thead button { font-size: inherit; width: 100%; }
    thead th:nth-child(2) { width: 32px; }thead th:nth-child(3) { width: 33%; }
    .rank { width: 32px; }.rank-change { min-width: 0; font-size: 10px; }
    .asset-cell { position: relative; }.select-row { min-height: 44px; padding-right: 44px; column-gap: var(--space-xs); }.select-row span { display: none; }
    .mobile-favorite { position: absolute; top: 4px; right: 0; width: 44px; min-width: 44px; padding: 0; background: transparent; border: 0; }
    .mobile-sort-basis, .mobile-movement { display: block; font-size: 10px; color: var(--muted); overflow-wrap: anywhere; line-height: 1.5; }
    .mobile-movement span { display: block; }
    .indicator { font-size: 10px; }.numeric { white-space: normal; overflow-wrap: anywhere; }
    .turnover-unit { display: block; }
    .detail-back { width: 100%; text-align: left; color: var(--focus); margin-bottom: var(--space-xs); }
    .chart-empty { padding: var(--space-lg); }
  }
  @media (max-width: 380px) {
    .check { font-size: 10px; }.numeric { font-size: 11px; }.select-row strong { font-size: 12px; }
    .ranking-conditions summary > span { font-size: 10px; }.saved-view-management summary { font-size: 11px; }
  }
</style>
