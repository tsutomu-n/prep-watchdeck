<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { page } from "$app/state";
  import ThemeSelector from "$lib/components/ThemeSelector.svelte";
  import FontSelector from "$lib/components/FontSelector.svelte";
  import DailyReferenceSetting from "$lib/components/DailyReferenceSetting.svelte";
  import ReferenceChart from "$lib/components/ranking/ReferenceChart.svelte";
  import type { RankedRow, RankingResponse } from "$lib/generated/ranking-response";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import { filterSortRankingRows, type RankingSort } from "$lib/market/market-view";
  import { formatPrice } from "$lib/market/universe-view";
  import { favoriteKey, readUserWorkspace, setFavorite } from "$lib/market/user-workspace";
  import { recordRecentMarket } from "$lib/market/recent-markets";
  import type { FavoriteTarget, UserWorkspace } from "$lib/server/user-workspace-repository";
  import { DEFAULT_REFERENCE_TIME, formatPriceChange } from "$lib/market/price-change";
  import {
    CHART_INTERVAL_KEY, RANKING_MAX_AGE_MS, approvedWidgetSymbol, indicatorLabel, matchesRankingQuery,
    rankChangeLabel, rankingQuery, rankingRowStateLabel, rankingStateLabel, rankingTimestamp, readChartInterval, referenceLabel,
    turnoverLabel, type ChartInterval, type RankingOrder, type RankingPeriod
  } from "$lib/market/ranking";

  let { market, legacyEntry = false }: {
    market: MarketArtifactBundle | null; legacyEntry?: boolean;
  } = $props();
  let period = $state<RankingPeriod>("15m");
  let order = $state<RankingOrder>("gainers");
  let reference = $state(DEFAULT_REFERENCE_TIME);
  let referenceReady = $state(false);
  let minimum = $state(0);
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
  let lastSelected = $state<RankedRow | null>(null);
  let selectedId = $state<string | null>(null);
  let selectedRemoved = $state(false);
  let mounted = $state(false);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let storageMessage = $state<string | null>(null);
  let now = $state(Date.now());
  let chartSection: HTMLElement;
  let controller: AbortController | null = null;
  let requestId = 0;
  let refreshTimer: ReturnType<typeof setTimeout> | undefined;

  const query = $derived.by(() => {
    try { return rankingQuery(period, reference, order, minimum).toString(); }
    catch { return null; }
  });
  const selected = $derived(data?.rows.find((row) => row.id === selectedId) ?? lastSelected);
  const nativeCandidates = $derived(selected?.originals.flatMap((original) =>
    (market?.universe.items ?? []).filter((instrument) =>
      instrument.active &&
      instrument.venueInstrumentId === original.instrumentId &&
      instrument.venueInstrumentVersionId === original.versionId
    )
  ) ?? []);
  const symbol = $derived(selectedRemoved ? null : approvedWidgetSymbol(selected));
  const stale = $derived(Boolean(data && (data.stale || now - data.cutoff > RANKING_MAX_AGE_MS)));
  const comparisonExpired = $derived(stale || Boolean(data?.previousCutoff && now - data.previousCutoff > RANKING_MAX_AGE_MS));
  const visibleRows = $derived.by(() => {
    const current = filterSortRankingRows(data?.rows ?? [], {
      search, venue, includeUnranked, minRatio, ratioPeriod, minDayPosition, maxDayPosition,
      sort, direction
    }).filter((row) => !favoritesOnly || Boolean(
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
    }).length - visibleRows.length) : 0);
  const selectedFiltered = $derived(Boolean(selectedId && data && !visibleRows.some((row) => row.id === selectedId)));
  const quantityUnverified = $derived((data?.rows ?? []).reduce((count, row) =>
    count + row.originals.filter((item) => item.multiplier === null).length, 0));
  const widgetReview = $derived((data?.rows ?? []).filter((row) => row.widget.status === "review").length);

  async function refresh(parameters: string, clear = false) {
    controller?.abort(); controller = new AbortController();
    const current = ++requestId;
    loading = true; error = null;
    if (clear) data = null;
    try {
      const response = await fetch(`/api/rankings?${parameters}`, { signal: controller.signal });
      if (!response.ok) throw new Error("ランキングの更新を待っています。専用収集の起動・取得状況を確認してください。");
      const payload: RankingResponse = await response.json();
      if (current !== requestId || !matchesRankingQuery(payload, new URLSearchParams(parameters))) return;
      data = payload; now = Date.now();
      if (selectedId) {
        const updated = payload.rows.find((row) => row.id === selectedId);
        selectedRemoved = !updated;
        if (updated) lastSelected = updated;
      }
    } catch (cause) {
      if (current === requestId && !(cause instanceof DOMException && cause.name === "AbortError")) {
        error = cause instanceof Error ? cause.message : "ランキングを取得できませんでした";
      }
    } finally { if (current === requestId) loading = false; }
  }

  function schedule() {
    const time = Date.now();
    let target = Math.floor(time / 60_000) * 60_000 + 12_000;
    if (target <= time) target += 60_000;
    refreshTimer = setTimeout(() => {
      if (query) void refresh(query);
      schedule();
    }, target - time);
  }

  onMount(() => {
    const selectedFromUrl = page.url.searchParams.get("selected");
    if (selectedFromUrl && /^[A-Za-z0-9:._-]{1,160}$/.test(selectedFromUrl)) {
      selectedId = selectedFromUrl;
    }
    const loadWorkspace = () => {
      if (document.visibilityState !== "hidden") {
        void readUserWorkspace().then((value) => { workspace = value; workspaceError = null; })
          .catch(() => workspaceError = "お気に入りを読み込めません");
      }
    };
    loadWorkspace();
    document.addEventListener("visibilitychange", loadWorkspace);
    if (!legacyEntry) {
      period = "24h";
      order = "turnover";
    }
    const params = page.url.searchParams;
    try {
      const requestedPeriod = params.get("period") as RankingPeriod | null;
      const requestedOrder = params.get("order") as RankingOrder | null;
      const requestedReference = params.get("dailyReferenceJst");
      const requestedMinimum = params.get("minTurnover");
      if (requestedPeriod && requestedOrder && requestedReference && requestedMinimum) {
        rankingQuery(requestedPeriod, requestedReference, requestedOrder, Number(requestedMinimum));
        period = requestedPeriod;
        order = requestedOrder;
        reference = requestedReference;
        minimum = Number(requestedMinimum);
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
        "return15m", "return1h", "return24h", "ratio15m", "ratio1h", "dayPosition"].includes(requestedSort)) {
        sort = requestedSort as RankingSort;
      }
      direction = params.get("direction") === "desc" ? "desc" : "asc";
    } catch { /* Invalid legacy query leaves safe defaults visible. */ }
    try { interval = readChartInterval(window.localStorage); } catch { interval = "15"; }
    mounted = true;
    const clock = setInterval(() => now = Date.now(), 10_000);
    const visible = () => { if (!document.hidden && query) void refresh(query); };
    document.addEventListener("visibilitychange", visible);
    schedule();
    return () => {
      controller?.abort(); clearTimeout(refreshTimer); clearInterval(clock);
      document.removeEventListener("visibilitychange", visible);
      document.removeEventListener("visibilitychange", loadWorkspace);
    };
  });

  $effect(() => {
    if (!mounted || !referenceReady || !query) return;
    const parameters = query;
    untrack(() => { limit = 50; void refresh(parameters, true); });
  });

  $effect(() => {
    if (!mounted) return;
    try { window.localStorage.setItem(CHART_INTERVAL_KEY, interval); storageMessage = null; }
    catch { storageMessage = "チャートの足設定は、この画面だけに適用しています"; }
  });

  async function select(row: RankedRow) {
    selectedId = row.id; lastSelected = row; selectedRemoved = false;
    try {
      recordRecentMarket(window.localStorage, {
        key: `reference:${row.id}`, label: `${row.asset} · 参照市場`,
        href: `/?mode=reference&selected=${encodeURIComponent(row.id)}`
      });
    } catch { /* The current selection remains usable without browser storage. */ }
    await tick();
    if (window.matchMedia("(max-width: 960px)").matches) chartSection?.scrollIntoView({ block: "start" });
  }

  function chooseSort(column: RankingSort) {
    if (sort === column) direction = direction === "asc" ? "desc" : "asc";
    else {
      sort = column;
      direction = ["referenceClose", "returnPct", "quoteTurnover", "return15m", "return1h",
        "return24h", "ratio15m", "ratio1h", "dayPosition"].includes(column) ? "desc" : "asc";
    }
  }

  function resetView() {
    search = ""; venue = "all"; includeUnranked = false; favoritesOnly = false; minRatio = null;
    minDayPosition = null; maxDayPosition = null; sort = "server"; direction = "asc";
    preset = "standard"; lockedIds = null;
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
            mode: "reference", period, order, reference, minimum, search, venue,
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
      returnSort: sort, returnDirection: direction
    });
    return `/?${query}`;
  }
</script>

<svelte:head><title>デイトレランキング | Prep Watchdeck</title></svelte:head>

<main class="ranking-page">
  <header class="topbar">
    <div><a class="back" href="/?mode=native">← 取引所別</a><h1>デイトレランキング</h1>
      <p>Bitget / Hyperliquid / Aster の取扱い銘柄を、外部参照でまとめて比較。</p></div>
    <div class="preferences"><ThemeSelector /><FontSelector /></div>
  </header>

  <section class="controls" aria-label="ランキング条件">
    <label>比較期間<select aria-label="ランキングの比較期間" bind:value={period}>
      <option value="15m">15分</option><option value="1h">1時間</option>
      <option value="24h">直近24時間</option><option value="daily">JST基準時刻から</option>
    </select></label>
    <label>並び順<select aria-label="ランキングの並び順" bind:value={order}>
      <option value="gainers">上昇率</option><option value="losers">下落率</option><option value="turnover">売買代金</option>
    </select></label>
    <label>売買代金の下限 · USDT<input aria-label="売買代金の下限" type="number" min="0" max="1000000000000000000" step="any" bind:value={minimum} /></label>
    <DailyReferenceSetting bind:value={reference} bind:ready={referenceReady} />
  </section>

  {#if !query}<p class="notice" role="alert">売買代金の下限は0以上の数値を指定してください。</p>{/if}
  {#if error}<p class="notice" role="status">{error} <button type="button" onclick={() => query && refresh(query)}>再試行</button></p>{/if}
  {#if stale}<p class="notice" role="status">更新が停止しています。表示値は {data ? rankingTimestamp(data.cutoff) : ""} JST 時点です。</p>{/if}
  {#if data?.rosterStale}<p class="notice">取扱い名簿の更新が止まっています。現在の上場状況は未確認です。</p>{/if}

  <div class="comparison-status" aria-live="polite">
    {#if data}
      <div><span>比較時刻 · JST</span><strong>{rankingTimestamp(data.anchor)} → {rankingTimestamp(data.cutoff)}</strong></div>
      <div><span>対象 / 参照対応 / 比較可能</span><strong>{data.coverage.cryptoRows} / {data.coverage.supported} / {data.coverage.valid} 銘柄</strong></div>
      <div><span>現在の条件での順位</span><strong>{data.coverage.ranked} 銘柄 {#if minimum > 0}· 下限で絞込み{/if}</strong></div>
      <span class="refresh-state">{loading ? "更新中" : stale ? "更新停止" : "毎分更新"}</span>
    {:else}<p>{loading ? "全対象のランキングを読み込んでいます" : "ランキングはまだ利用できません"}</p>{/if}
  </div>
  <p class="metric-note">売買代金は同じ比較期間における、参照取引所の当該契約のUSDT建て合計です。3取引所や市場全体の合計ではありません。</p>
  <p class="metric-note">順位変化は同じ条件での1分前の順位 − 現順位です。+は順位上昇、−は順位低下、0は同順位。「新規」は前回だけ順位外だった銘柄です。</p>
  <p class="metric-note">売買代金の平常比は、直近24時間内の同期間中央値との比較です（最新窓を除く15分95窓・1時間23窓）。当日位置はJST 00:00からの高安に対する終値の位置で、0%が安値、100%が高値です。</p>

  <div class="workspace">
    <section class="ranking-list" aria-labelledby="list-title">
      <div class="list-heading"><h2 id="list-title">{order === "gainers" ? "上昇率" : order === "losers" ? "下落率" : "売買代金"}ランキング</h2><span>{visibleRows.length} 件</span></div>
      <div class="list-controls">
        <label class="search">銘柄検索<input aria-label="ランキングの銘柄検索" type="search" bind:value={search} placeholder="BTC、ETH、契約名" /></label>
        <label class="check"><input type="checkbox" bind:checked={includeUnranked} />順位外・未対応も表示</label>
        <label class="check"><input type="checkbox" bind:checked={favoritesOnly} />お気に入りのみ</label>
      </div>
      {#if workspaceError}<p class="notice" role="alert">{workspaceError}</p>{/if}
      <div class="list-controls">
        <label>保存した表示<select aria-label="保存した表示" value={selectedViewId}
          onchange={(event) => applySavedView(event.currentTarget.value)}>
          <option value="">選択してください</option>
          {#each workspace?.savedViews.filter((item) => item.view.mode === "reference") ?? [] as saved}
            <option value={saved.id}>{saved.name}</option>
          {/each}
        </select></label>
        <label>表示名<input aria-label="表示名" maxlength="80" bind:value={viewName} /></label>
        <button type="button" disabled={viewBusy || !viewName.trim() || !workspace} onclick={saveCurrentView}>表示条件を保存</button>
        <button type="button" disabled={viewBusy || !selectedViewId} onclick={removeSavedView}>保存した表示を削除</button>
      </div>
      <div class="list-controls">
        <label>取扱い取引所<select aria-label="取扱い取引所" bind:value={venue}>
          <option value="all">すべて</option><option value="bitget">Bitget</option>
          <option value="hyperliquid">Hyperliquid</option><option value="aster">Aster</option>
        </select></label>
        <label>表示列<select aria-label="表示列プリセット" bind:value={preset}>
          <option value="standard">標準</option><option value="movement">値動き</option>
        </select></label>
        <label>平常比期間<select aria-label="平常比期間" bind:value={ratioPeriod}>
          <option value="15m">15分</option><option value="1h">1時間</option>
        </select></label>
        <label>平常比下限<input aria-label="平常比下限" type="number" min="0" step="any"
          value={minRatio ?? ""} oninput={(event) => minRatio = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <label>当日位置の下限 %<input aria-label="当日位置の下限" type="number" min="0" max="100" step="any"
          value={minDayPosition ?? ""} oninput={(event) => minDayPosition = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <label>当日位置の上限 %<input aria-label="当日位置の上限" type="number" min="0" max="100" step="any"
          value={maxDayPosition ?? ""} oninput={(event) => maxDayPosition = event.currentTarget.value === "" ? null : Number(event.currentTarget.value)} /></label>
        <button type="button" onclick={() => lockedIds = lockedIds ? null : visibleRows.map((row) => row.id)}>
          {lockedIds ? "行順固定を解除" : "行順を固定"}
        </button>
        <button type="button" onclick={resetView}>条件をクリア</button>
      </div>
      {#if addedRows}<p class="search-note">新しい行が {addedRows} 件あります。固定解除で表示します。</p>{/if}
      <p class="search-note">検索は順位を変えません。並び順と売買代金下限は全対応銘柄へ適用されます。</p>
      <div class="table-scroll" aria-busy={loading}>
        <table>
          <thead><tr>
            <th scope="col">保存</th>
            <th scope="col">全体順位</th>
            <th scope="col" aria-sort={sort === "asset" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("asset")}>銘柄 / 取扱い</button></th>
            <th scope="col" aria-sort={sort === "referenceClose" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("referenceClose")}>参照終値</button></th>
            <th scope="col" aria-sort={sort === "returnPct" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("returnPct")}>騰落率</button></th>
            <th scope="col" aria-sort={sort === "quoteTurnover" ? direction === "asc" ? "ascending" : "descending" : undefined}><button type="button" onclick={() => chooseSort("quoteTurnover")}>売買代金 · USDT</button></th>
            {#if preset === "movement"}<th scope="col">15分 / 1時間 / 24時間</th>{/if}
          </tr></thead>
          <tbody>
            {#each visibleRows.slice(0, limit) as row (row.id)}
              <tr class:selected={selectedId === row.id} data-testid="ranking-row" data-asset={row.asset}>
                <td><button type="button" disabled={!referenceTarget(row)}
                  title={workspace?.favorites.some((entry) => entry.kind === "reference" && entry.id === row.id) && !referenceFavoriteCurrent(row)
                    ? "参照対応が変わりました。確認してから再登録してください" : undefined}
                  aria-label={`${row.asset}をお気に入り${(favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)) ? "解除" : "登録"}`}
                  aria-pressed={favoriteIntent[`reference:${row.id}`] ?? referenceFavoriteCurrent(row)}
                  onclick={() => toggleFavorite(row)}>★</button></td>
                <td class="rank">{row.rank ?? "—"}{#if sort === "server"}<small class="rank-change" data-testid="rank-change">{rankChangeLabel(row, comparisonExpired)}</small>{/if}</td>
                <th scope="row"><button type="button" class="select-row" aria-pressed={selectedId === row.id} onclick={() => select(row)}>
                  <strong>{row.asset}</strong><span>{row.venues.map((v) => v === "hyperliquid" ? "Hyperliquid" : v === "bitget" ? "Bitget" : "Aster").join(" · ")}</span>
                  <small>{referenceLabel(row)}</small>
                </button></th>
                <td class="numeric">{row.referenceClose.status === "ready" ? formatPrice(row.referenceClose.value) : "未取得"}</td>
                <td class="numeric change" class:up={(row.returnPct ?? 0) > 0} class:down={(row.returnPct ?? 0) < 0}>
                  {#if row.returnPct !== null}{formatPriceChange(row.returnPct)}{:else}<span class="missing">{rankingRowStateLabel(row)}</span>{/if}
                  <small class="indicator" data-testid="day-position">当日位置 <span class:missing={row.dayRangePosition.status !== "ready"}>{indicatorLabel(row.dayRangePosition, "%")}</span></small>
                </td>
                {#if preset === "movement"}
                  <td class="numeric">{#each ["15m", "1h", "24h"] as window}
                    <span>{window}: {row.windows[window as "15m" | "1h" | "24h"].returnPct === null
                      ? "未取得" : formatPriceChange(row.windows[window as "15m" | "1h" | "24h"].returnPct!)}</span>
                  {/each}</td>
                {/if}
                <td class="numeric turnover">{#if row.quoteTurnover !== null}<span title={`${row.quoteTurnover.toLocaleString("en-US")} USDT`}>{turnoverLabel(row.quoteTurnover)}</span>{:else}<span class="missing">未取得</span>{/if}
                  <small class="indicator" data-testid="turnover-ratio">平常比 <span class:missing={row.turnoverRatio.status !== "ready"}>{indicatorLabel(row.turnoverRatio, "倍")}</span></small>
                  {#if row.rank === null && row.returnPct !== null}<small>{rankingStateLabel(row.state)}</small>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if !loading && visibleRows.length === 0}<p class="empty">この条件の銘柄はありません。順位外・未対応の表示でも状態を確認できます。</p>{/if}
      </div>
      {#if visibleRows.length > limit}<button class="more" type="button" onclick={() => limit += 50}>さらに50件を表示（{limit} / {visibleRows.length}）</button>{/if}
      {#if data}
        <details class="coverage"><summary>対応範囲と除外理由</summary>
          <p>元の {data.coverage.sourceInstruments} 契約を {data.coverage.rows} 行に整理。Widget対応 {data.coverage.widgetSupported} 銘柄。</p>
          <p>元契約の数量換算が未確認: {quantityUnverified} 契約。Chart対応が未確認: {widgetReview} 銘柄。各確認状態はランキングの参照対応と別に管理します。</p>
          <dl>{#each Object.entries(data.coverage.reasons) as [state, count]}<div><dt>{rankingStateLabel(state as RankedRow["state"]) ?? state}</dt><dd>{count}</dd></div>{/each}</dl>
          <p>名簿確認: {rankingTimestamp(data.rosterGeneratedAt)} JST</p>
        </details>
      {/if}
    </section>

    <section class="chart-section" aria-labelledby="chart-title" bind:this={chartSection}>
      {#if selected}
        <div class="selected-heading"><span>選択中の参照契約</span><h2 id="chart-title">{selected.asset}</h2><p>{referenceLabel(selected)}</p></div>
        <div class="native-candidates">
          <button type="button" onclick={() => moveSelected(-1)} disabled={visibleRows.findIndex((row) => row.id === selectedId) <= 0}>前の銘柄</button>
          <button type="button" onclick={() => moveSelected(1)} disabled={visibleRows.findIndex((row) => row.id === selectedId) >= visibleRows.length - 1}>次の銘柄</button>
        </div>
        {#if data && !selectedRemoved}
          <dl class="selected-metrics" data-testid="selected-metrics">
            <div><dt>1分前からの順位変化</dt><dd>{rankChangeLabel(selected, comparisonExpired)}</dd></div>
            <div><dt>売買代金の平常比</dt><dd>{indicatorLabel(selected.turnoverRatio, "倍")}</dd></div>
            <div><dt>JST当日の高安位置 · 00:00から</dt><dd>{indicatorLabel(selected.dayRangePosition, "%")}</dd></div>
          </dl>
        {/if}
        {#if selected.state === "mapping_review"}<p class="selection-notice">{rankingRowStateLabel(selected)}。確認できるまで順位とチャートに含めません。</p>
        {:else if selected.state === "unsupported"}<p class="selection-notice">{rankingRowStateLabel(selected)}。順位とチャートの対象外です。</p>{/if}
        {#if selected.originals.some((item) => item.multiplier === null)}
          <p class="selection-notice" data-testid="quantity-review">元の取引所の数量換算は未確認です。{#if selected.mappingStatus === "verified"}ランキングの数値は、確認済みの参照契約から計算しています。{/if}元契約への数量・価格の換算には利用できません。</p>
        {/if}
        {#if selectedRemoved}<p class="selection-notice">選択銘柄は更新後の対応表にありません。選択名を維持し、チャートを停止しています。</p>
        {:else if selectedFiltered}<p class="selection-notice">選択銘柄は現在の一覧条件の対象外です。選択は維持しています。</p>{/if}
        {#if symbol}<ReferenceChart {symbol} bind:interval />{:else}<div class="chart-empty"><h3>この参照契約のWidgetは利用できません</h3><p>{selected.widget.status === "review" ? "チャートの対応確認が必要です。" : "対応するチャートが確認できません。"}</p>{#if selected.mappingStatus === "verified"}<p>Chartの対応状況は、ランキングの数値計算には影響しません。</p>{/if}</div>{/if}
        <div class="native-candidates" aria-label="現在の取扱い契約">
          {#each nativeCandidates as instrument (instrument.venueInstrumentId)}
            <a href={nativeHref(instrument.venueInstrumentId, instrument.venueInstrumentVersionId)}>
              {instrument.venue} · {instrument.sourceSymbol} のnative詳細
            </a>
          {:else}
            <p>現在の名簿でIDとversionが一致するnative契約はありません。</p>
          {/each}
        </div>
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
  .native-candidates { display: flex; flex-wrap: wrap; gap: var(--space-sm); padding: var(--space-md) 0; }
  .native-candidates a { color: var(--focus); border: 1px solid var(--line-strong); padding: var(--space-sm); }
  .ranking-page { padding: var(--space-page); color: var(--text); max-width: 1900px; margin: 0 auto; }
  .topbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--space-lg); align-items: end; padding: var(--space-sm) 0 var(--space-lg); border-bottom: 1px solid var(--line-strong); }
  h1 { margin: var(--space-sm) 0; font-size: var(--type-title-lg-size); line-height: var(--type-title-lg-leading); }
  .topbar p, .metric-note, .search-note { margin: var(--space-xs) 0; color: var(--muted); font-size: var(--type-body-sm-size); line-height: 1.5; }
  .back { color: var(--focus); font-size: var(--type-body-sm-size); text-decoration: none; }
  .preferences { display: flex; flex-wrap: wrap; gap: var(--space-md); }
  .controls { display: grid; grid-template-columns: 140px 140px minmax(170px, 1fr) minmax(220px, 1fr); align-items: end; gap: var(--space-md); padding: var(--space-md) 0; }
  label { display: grid; gap: var(--space-xs); color: var(--muted); font-size: var(--type-label-caps-size); min-width: 0; }
  input, select, .notice button { min-width: 0; min-height: var(--control-height-dense); border: 1px solid var(--line-strong); border-radius: 0; background: var(--surface); color: var(--text); padding: 0 var(--space-sm); font: inherit; font-size: var(--type-body-sm-size); }
  .notice { padding: var(--space-sm) var(--space-md); border-left: 3px solid var(--warning-border); background: var(--surface); color: var(--warning); font-size: var(--type-body-sm-size); }
  .comparison-status { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-lg); background: var(--panel-strong); padding: var(--space-md); border-block: 1px solid var(--line); min-height: 62px; }
  .comparison-status > div { display: grid; gap: var(--space-xs); }
  .comparison-status span { color: var(--muted); font-size: var(--type-label-caps-size); }
  .comparison-status strong { font-size: var(--type-data-md-size); font-variant-numeric: tabular-nums; }
  .refresh-state { margin-left: auto; }
  .metric-note { margin: var(--space-sm) 0 var(--space-lg); font-size: var(--type-label-caps-size); }
  .workspace { display: grid; grid-template-columns: minmax(470px, .95fr) minmax(0, 1.05fr); gap: var(--space-lg); align-items: start; }
  .ranking-list, .chart-section { min-width: 0; }
  .list-heading { display: flex; justify-content: space-between; align-items: center; padding: var(--space-sm) 0; }
  .list-heading h2 { margin: 0; font-size: var(--type-heading-md-size); }
  .list-heading > span { font-size: var(--type-body-sm-size); color: var(--muted); }
  .list-controls { display: flex; gap: var(--space-md); align-items: end; padding: var(--space-sm) 0; }
  .search { flex: 1; }
  .check { display: flex; align-items: center; min-height: var(--control-height-dense); white-space: nowrap; }
  .check input { min-height: 0; accent-color: var(--focus); }
  .search-note { font-size: var(--type-label-caps-size); }
  .table-scroll { max-height: 640px; overflow: auto; border-block: 1px solid var(--line-strong); }
  table { border-collapse: collapse; width: 100%; font-size: var(--type-body-sm-size); }
  th, td { padding: var(--space-sm); border-bottom: 1px solid var(--line); vertical-align: middle; }
  thead th { position: sticky; top: 0; z-index: 1; background: var(--panel-strong); color: var(--muted); font-size: var(--type-label-caps-size); font-weight: 500; text-align: right; white-space: nowrap; }
  thead th:nth-child(2) { text-align: left; }
  tbody th { font-weight: 500; text-align: left; }
  tr { background: var(--panel); }
  tr.selected { background: var(--panel-selected); box-shadow: inset 3px 0 var(--focus); }
  .rank { color: var(--muted); font-variant-numeric: tabular-nums; width: 38px; text-align: right; }
  .rank-change { display: block; font-size: var(--type-label-caps-size); white-space: normal; overflow-wrap: anywhere; min-width: 50px; }
  .selected-metrics { color: var(--subtle); font-size: var(--type-body-sm-size); line-height: 1.6; }
  .selected-metrics div { display: flex; justify-content: space-between; flex-wrap: wrap; gap: var(--space-xs); }
  .selected-metrics dd { margin: 0; font-variant-numeric: tabular-nums; }
  .indicator { display: block; color: var(--muted); font-size: var(--type-label-caps-size); white-space: normal; }
  .select-row { display: grid; width: 100%; gap: var(--space-xxs); border: 0; border-radius: 0; padding: 0; background: transparent; color: var(--text); text-align: left; cursor: pointer; font: inherit; min-height: 42px; }
  .select-row strong { font-size: var(--type-data-md-size); }
  .select-row span, .select-row small { color: var(--muted); font-size: var(--type-label-caps-size); overflow-wrap: anywhere; }
  .numeric { font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
  .up { color: var(--up); }.down { color: var(--down); }
  .missing { color: var(--quality-risk); font-size: var(--type-label-caps-size); white-space: normal; }
  .turnover small { display: block; color: var(--muted); font-size: var(--type-label-caps-size); white-space: normal; }
  .more { width: 100%; min-height: 44px; border: 1px solid var(--line-strong); background: var(--surface); color: var(--text); font: inherit; font-size: var(--type-body-sm-size); cursor: pointer; }
  .empty { padding: var(--space-lg); color: var(--muted); line-height: 1.6; font-size: var(--type-body-sm-size); }
  .coverage, .contracts { border-bottom: 1px solid var(--line); padding: var(--space-sm) 0; font-size: var(--type-body-sm-size); color: var(--muted); }
  summary { cursor: pointer; min-height: 34px; display: list-item; align-content: center; }
  .coverage dl { display: grid; gap: var(--space-xs); }.coverage dl div { display: flex; justify-content: space-between; }.coverage dd { font-variant-numeric: tabular-nums; }
  .chart-section { position: sticky; top: var(--space-sm); scroll-margin-top: var(--space-md); }
  .selected-heading { border-bottom: 1px solid var(--line-strong); padding: var(--space-sm) 0 var(--space-md); }
  .selected-heading > span { color: var(--muted); font-size: var(--type-label-caps-size); }
  .selected-heading h2 { margin: var(--space-xs) 0; font-size: var(--type-title-lg-size); }
  .selected-heading p { color: var(--subtle); font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
  .selection-notice { border-left: 2px solid var(--warning-border); padding: var(--space-sm); color: var(--warning); font-size: var(--type-body-sm-size); }
  .chart-empty { display: flex; flex-direction: column; justify-content: center; min-height: 320px; padding: var(--space-xl); border: 1px solid var(--line); background: var(--panel); }
  .chart-empty > span, .chart-empty p { color: var(--muted); font-size: var(--type-body-sm-size); line-height: 1.7; }.chart-empty h2, .chart-empty h3 { font-size: var(--type-heading-md-size); }
  @media (max-width: 960px) {
    .workspace { grid-template-columns: minmax(0, 1fr); }.chart-section { position: static; }
    .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }.table-scroll { max-height: 500px; }
    input, select { min-height: var(--control-height-touch); }.check { min-height: 44px; }
    .topbar { align-items: stretch; }.preferences { width: 100%; }.comparison-status { gap: var(--space-md); }
  }
  @media (max-width: 560px) {
    .controls :global(.daily-reference-setting) { grid-column: 1 / -1; }
    .preferences { display: grid; grid-template-columns: minmax(0, 1fr); }.list-controls { flex-direction: column; align-items: stretch; gap: 0; }
    .controls { gap: var(--space-sm); }.comparison-status { display: grid; grid-template-columns: minmax(0, 1fr); }.refresh-state { margin-left: 0; }
    thead th { padding: var(--space-sm) var(--space-xs); font-size: 10px; }th, td { padding: var(--space-sm) var(--space-xs); }
    .rank { width: 24px; }.select-row { min-height: 62px; }.select-row span { max-width: 130px; }.numeric { font-size: var(--type-body-sm-size); }
    .turnover { width: 76px; }.change { width: 76px; }.chart-empty { padding: var(--space-lg); }
  }
</style>
