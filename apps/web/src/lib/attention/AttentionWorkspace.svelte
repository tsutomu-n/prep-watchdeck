<script lang="ts">
  import { onMount } from "svelte";
  import type { AttentionResponse, AttentionRow } from "$lib/generated/attention-response";
  import type { FavoriteTarget } from "$lib/server/user-workspace-repository";
  import { readUserWorkspace, setFavorite } from "$lib/market/user-workspace";
  import { parseAttention } from "./contract";
  import { COMPONENTS, COMPONENT_LABELS, displayScore, isFavorite, matchingFavorites, nativeLink,
    reasonLabel, referenceLink, visibleRows, type ComponentName } from "./attention";

  let response = $state<AttentionResponse | null>(null);
  let component = $state<ComponentName>("confluence");
  let query = $state("");
  let readyOnly = $state(false);
  let prioritizeFavorites = $state(false);
  let favorites = $state<FavoriteTarget[]>([]);
  let favoritesLoaded = $state(false);
  let favoritePending = $state(false);
  let favoriteError = $state("");
  let readError = $state("");
  const directions = { up: "↑ 上昇", down: "↓ 下落", flat: "→ 横ばい", mixed: "混在", unknown: "—" };
  const time = (value: number) => new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit"
  }).format(value);
  let favoriteIds = $derived(new Set(response?.rows.filter(row => isFavorite(row, favorites)).map(row => row.assetId) ?? []));
  let rows = $derived(response ? visibleRows(response, component, query, readyOnly, prioritizeFavorites, favoriteIds) : []);
  let statusLabel = $derived(readError ? "更新停止" : response?.status === "stale" ? "データが古くなっています" :
    response?.status === "ready" ? "更新中" : response?.status === "partial" ? "一部の成分は未算出" : "データを待っています");

  async function toggleFavorite(row: AttentionRow) {
    if (favoritePending || !favoritesLoaded || !row.referenceKey) return;
    favoritePending = true;
    favoriteError = "";
    try {
      const matches = matchingFavorites(row, favorites);
      if (matches.length) {
        for (const target of matches) favorites = (await setFavorite(target, false)).favorites;
      } else {
        favorites = (await setFavorite({ kind: "reference", id: row.assetId, referenceKey: row.referenceKey,
          originals: row.originals.map(original => `${original.instrumentId}:${original.versionId}`) }, true)).favorites;
      }
    } catch (cause) { favoriteError = cause instanceof Error ? cause.message : "お気に入りを保存できません"; }
    finally { favoritePending = false; }
  }

  onMount(() => {
    let disposed = false;
    let busy = false;
    let controller: AbortController | null = null;
    async function refresh() {
      if (busy || document.hidden) return;
      busy = true;
      controller = new AbortController();
      const timeout = setTimeout(() => controller?.abort(), 6000);
      try {
        const result = await fetch("/api/attention", { cache: "no-store", signal: controller.signal });
        if (!result.ok) throw new Error("注目データの取得を待っています");
        const next = parseAttention(await result.json());
        if (!disposed) { response = next; readError = ""; }
      } catch {
        if (!disposed) {
          readError = "更新を確認できません。最後に確認できたデータの時刻を表示しています。";
          if (response) response = { ...response, status: "stale" };
        }
      } finally { clearTimeout(timeout); busy = false; }
    }
    void readUserWorkspace().then(workspace => {
      if (!disposed) { favorites = workspace.favorites; favoritesLoaded = true; }
    }).catch(() => { if (!disposed) favoriteError = "お気に入りを読み込めません"; });
    void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    const visible = () => { if (!document.hidden) void refresh(); };
    document.addEventListener("visibilitychange", visible);
    return () => { disposed = true; clearInterval(timer); controller?.abort(); document.removeEventListener("visibilitychange", visible); };
  });
</script>

<main class="attention-workspace">
  <header>
    <div><p class="eyebrow">ATTENTION</p><h1>市場の注目</h1></div>
    <div class="update" class:warning={response?.status !== "ready"}>
      <strong role="status">{statusLabel}</strong>
      {#if response}<span>参照基準 {time(response.inputs.rankingCutoff)} JST</span>{/if}
    </div>
  </header>
  <p class="explanation">注目の強さを市場内の相対スコアで表示。方向は別欄で確認できます。</p>
  {#if readError}<p class="notice" role="alert">{readError}</p>{/if}
  {#if favoriteError}<p class="notice" role="alert">{favoriteError}</p>{/if}

  <div class="controls">
    <label>注目成分<select bind:value={component}>
      {#each ["confluence", ...COMPONENTS] as name}<option value={name}>{COMPONENT_LABELS[name as ComponentName]}</option>{/each}
    </select></label>
    <label class="search">銘柄検索<input type="search" bind:value={query} placeholder="BTC、ETH…" /></label>
    <label class="toggle"><input type="checkbox" bind:checked={readyOnly} />算出済みのみ</label>
    <label class="toggle"><input type="checkbox" bind:checked={prioritizeFavorites} />お気に入り優先</label>
  </div>

  {#if response}
    <div class="table-caption"><h2>{COMPONENT_LABELS[component]}</h2><span>{rows.length} / {response.coverage.rows} 銘柄 · 算出 {component === "confluence" ? response.coverage.confluenceReady : response.coverage.componentReady[component]}</span></div>
    <table aria-label="市場の注目一覧">
      <thead><tr><th scope="col">お気に入り</th><th scope="col">市場順位</th><th scope="col">銘柄</th><th scope="col">スコア</th><th scope="col">方向</th><th scope="col">成分充足 / 品質</th><th scope="col">チャート</th></tr></thead>
      <tbody>
        {#each rows as row (row.assetId)}
          {@const value = row.components[component]}
          <tr data-asset={row.asset}>
            <td class="favorite"><button aria-label={`${row.asset}をお気に入り${favoriteIds.has(row.assetId) ? "から削除" : "に追加"}`} aria-pressed={favoriteIds.has(row.assetId)} disabled={favoritePending || !favoritesLoaded || !row.referenceKey} onclick={() => toggleFavorite(row)}>{favoriteIds.has(row.assetId) ? "★" : "☆"}</button></td>
            <td class="rank" aria-label={`市場順位 ${value.rank ?? "未算出"}`}><span class="mobile-label">順位</span>{value.rank ?? "—"}{#if value.rankChange !== null}<small>{value.rankChange > 0 ? "+" : ""}{value.rankChange}</small>{/if}</td>
            <th scope="row" class="asset">{row.asset}</th>
            <td class="score"><span class="mobile-label">スコア</span>{displayScore(value.score)}</td>
            <td class="direction" class:up={value.direction === "up"} class:down={value.direction === "down"}>{directions[value.direction]}</td>
            <td class="quality"><strong>{row.readyComponentCount}/4 成分</strong>
              <span>基準 {time(row.dataAsOf)} JST</span>
              {#if value.reason}<span>{reasonLabel(value.reason)}</span>{/if}
              {#each row.qualityReasons as reason}<span>{reasonLabel(reason)}</span>{/each}
            </td>
            <td class="links">
              {#if referenceLink(row)}<a href={referenceLink(row)}>参照</a>{/if}
              {#each row.originals as original}
                {@const link = nativeLink(original)}
                {#if link}<a href={link}>{original.venue}</a>{/if}
              {/each}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    {#if !rows.length}<p class="empty">条件に合う銘柄がありません。</p>{/if}

    <details class="provenance"><summary>計算基準とデータの時刻</summary>
      <dl><dt>表示世代の判断時刻</dt><dd>{time(response.decisionAt)} JST</dd><dt>参照データの作成</dt><dd>{time(response.inputs.rankingGeneratedAt)} JST</dd>
        <dt>取引所指標の作成</dt><dd>{response.inputs.marketMetricsGeneratedAt === null ? "未取得" : `${time(response.inputs.marketMetricsGeneratedAt)} JST`}</dd>
        <dt>入力時刻の差</dt><dd>{response.inputs.inputSkewSeconds.toFixed(1)} 秒</dd><dt>算出ルール</dt><dd>{response.policyVersion}</dd><dt>銘柄対応の版</dt><dd>{response.inputs.rankingMapVersion}</dd></dl>
      <p>総合注目は4成分が揃う場合だけ算出します。スコアは利益や売買方向を表しません。お気に入りの並び替えは市場順位を変えません。</p>
      {#each response.inputs.qualityReasons as reason}<p>{reasonLabel(reason)}</p>{/each}
    </details>
    {#if response.shadowAllocations.length}
      <details class="provenance"><summary>監視候補の比較（試算）</summary><p>監視対象の入れ替え案です。現在の選択は変更しません。費用は推定値です。</p>
        {#each response.shadowAllocations as allocation}<p><strong>{allocation.policy.id}</strong> · {allocation.slots.length} 銘柄 · 入替率 {(allocation.churn * 100).toFixed(0)}% · 推定費用 {allocation.estimatedSwitchCost.toFixed(3)}</p>{/each}
      </details>
    {/if}
  {:else}<p class="empty">注目データを取得すると、成分ごとの順位と品質をここに表示します。</p>{/if}
</main>

<style>
  .attention-workspace { padding: 16px; max-width: 1600px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: end; gap: 12px; border-bottom: 1px solid var(--line-strong); padding-bottom: 12px; }
  h1 { font-size: 24px; margin: 4px 0 0; } .eyebrow { color: var(--focus); font-size: 11px; letter-spacing: .1em; margin: 0; }
  .update { display: grid; gap: 5px; text-align: right; color: var(--muted); } .update strong { color: var(--quality-good); } .update.warning strong { color: var(--warning); }
  .explanation { color: var(--muted); margin: 12px 0; } .notice { border-left: 3px solid var(--warning); padding: 10px; color: var(--warning); background: var(--panel-solid); }
  .controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; padding: 12px 0; }
  label { display: grid; gap: 5px; color: var(--muted); } input, select { color: var(--text); background: var(--panel-solid); border: 1px solid var(--line-strong); padding: 8px; min-height: 40px; border-radius: var(--radius-xs); max-width: 100%; }
  .search { flex: 1; min-width: 140px; max-width: 320px; } .search input { min-width: 0; width: 100%; } select { width: 100%; } .toggle { display: flex; align-items: center; min-height: 40px; gap: 6px; } .toggle input { min-height: auto; width: 16px; height: 16px; accent-color: var(--focus); }
  .table-caption { display: flex; gap: 12px; align-items: baseline; margin: 12px 0 8px; } h2 { font-size: 16px; margin: 0; } .table-caption span { color: var(--muted); }
  table { width: 100%; border-collapse: collapse; background: var(--panel-solid); } th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); } thead th { color: var(--muted); font-size: 11px; font-weight: 500; }
  .favorite { width: 44px; } button { border: 1px solid var(--line); background: transparent; color: var(--muted); width: 40px; height: 40px; font-size: 20px; cursor: pointer; } button[aria-pressed="true"] { color: var(--focus); } button:disabled { opacity: .5; cursor: default; }
  .rank, .score { font-variant-numeric: tabular-nums; } .score { font-size: 20px; font-weight: 750; } .rank small { display: block; color: var(--muted); } .asset { font-size: 15px; overflow-wrap: anywhere; } .direction { white-space: nowrap; } .up { color: var(--up); } .down { color: var(--down); }
  .quality strong { font-weight: 500; } .quality span { display: block; color: var(--muted); font-size: 11px; margin-top: 4px; } .links { max-width: 250px; } .links a { display: inline-flex; align-items: center; min-height: 40px; padding: 4px 8px; color: var(--text); text-decoration-color: var(--line-strong); }
  .mobile-label { display: none; } .empty { color: var(--muted); padding: 32px 0; text-align: center; }
  .provenance { border-top: 1px solid var(--line); padding: 12px 0; margin-top: 16px; color: var(--muted); } summary { color: var(--text); cursor: pointer; min-height: 32px; } dl { display: grid; grid-template-columns: 180px 1fr; gap: 8px; } dd { margin: 0; overflow-wrap: anywhere; }
  :is(button, a, input, select, summary):focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
  @media (max-width: 640px) {
    .attention-workspace { padding: 12px 8px; } header { align-items: start; } h1 { font-size: 21px; } .update { font-size: 11px; } .controls { gap: 8px 12px; } .controls > label:not(.toggle) { flex: 1; min-width: 140px; }
    input, select, button, .links a { min-height: 44px; } table, tbody { display: block; } thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
    tr { display: grid; grid-template-columns: 44px minmax(0, 1fr) 70px 80px; padding: 8px; border-bottom: 1px solid var(--line-strong); align-items: center; } th, td { padding: 4px; border: 0; min-width: 0; }
    .favorite { grid-row: 1 / 3; padding: 0; } .asset { grid-column: 2; grid-row: 1; } .rank { grid-column: 2; grid-row: 2; } .rank small { display: inline; margin-left: 6px; } .score { grid-column: 3; grid-row: 1 / 3; } .direction { grid-column: 4; grid-row: 1 / 3; }
    .mobile-label { display: inline; color: var(--muted); font-size: 10px; font-weight: 400; margin-right: 5px; } .score .mobile-label { display: block; } .quality { grid-column: 2 / 5; margin-top: 6px; } .links { grid-column: 2 / 5; max-width: none; } dl { grid-template-columns: 1fr; gap: 4px; } dd { margin-bottom: 8px; }
  }
</style>
