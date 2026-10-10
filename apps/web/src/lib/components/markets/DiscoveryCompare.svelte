<script lang="ts">
  import { onMount, tick } from "svelte";
  import { goto } from "$app/navigation";
  import type { DiscoveryResponse, DiscoveryRow, RawFeatureValue, DiscoveryEpisode } from "$lib/generated/discovery-response";
  import type { DiscoverySummary, DiscoverySummaryRow } from "$lib/generated/discovery-summary";
  import { DiscoveryGenerationChanged, readDiscoveryView, requestDiscovery } from "$lib/discovery/client";
  import type { ComparisonPin, UserWorkspace } from "$lib/server/user-workspace-repository";
  import type { DecisionHistory, DecisionInput } from "$lib/market/decisions";
  import { mergeDiscoveryEpisodes } from "$lib/discovery/history";
  import { episodeSkipped } from "$lib/market/decisions";
  import { favoriteKey, readUserWorkspace } from "$lib/market/user-workspace";
  import { comparisonPin, discoveryTarget, sameTarget } from "$lib/discovery/contract";
  import { nativeUniverseFresh } from "$lib/market/ranking-native";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import { formatFinite, formatPrice, formatTimestamp } from "$lib/market/universe-view";

  let workspace = $state<UserWorkspace | null>(null);
  let discovery = $state<DiscoverySummary | null>(null);
  let pinnedDiscovery = $state<DiscoveryResponse | null>(null);
  let pinnedRows = $derived(pinnedDiscovery?.rows ?? []);
  let history = $state<DecisionHistory | null>(null);
  let error = $state<string | null>(null);
  let unavailable = $state<string | null>(null);
  let busy = $state(false);
  let nativeConfirm = $state<{ pin: ComparisonPin; row: DiscoveryRow; instrumentId: string; version: number } | null>(null);
  let decisionFor = $state<{ pin: ComparisonPin; row: DiscoveryRow; action: "watch" | "skip"; id: string; snapshot: Record<string, unknown> } | null>(null);
  let reason = $state("");
  let confirmationRegion = $state<HTMLElement | null>(null);
  let reasonInput = $state<HTMLTextAreaElement | null>(null);
  let returnFocus: HTMLElement | null = null;
  let episodes = $state<DiscoveryEpisode[]>([]);
  let historyPaged = false;
  let updating = $state(false);
  let loading = false;
  let pendingLoad = false;
  let alive = true;
  let cursor = $state<string | null>(null);
  let cursorLoading = $state(false);
  let historyFilter = $state("");
  let candidates = $derived(discovery?.rows.filter(row => row.state === "matched" &&
    !episodeSkipped(history, row.episodeId)) ?? []);
  let pins = $derived(workspace?.pins ?? []);


  function pinnedIds() { return pins.filter(pin => pin.target.kind === "reference").map(pin => pin.target.id); }
  async function load() {
    if (loading) { pendingLoad = true; return; }
    loading = true;
    const ids = pinnedIds();
    try {
      const view = await readDiscoveryView(ids);
      if (!alive || JSON.stringify(ids) !== JSON.stringify(pinnedIds())) { pendingLoad = alive; return; }
      // Keep the previous complete view until both responses are from one generation.
      discovery = view.summary;
      pinnedDiscovery = view.detail;
      updating = false;
      unavailable = view.summary.status === "unavailable" ? `候補機能は利用不可です: ${view.summary.reason ?? "データ未取得"}` : null;
    } catch (cause) {
      if (!alive) return;
      updating = updating || cause instanceof DiscoveryGenerationChanged;
      unavailable = updating ? new DiscoveryGenerationChanged().message
        : cause instanceof Error ? cause.message : "候補機能を利用できません";
    } finally {
      loading = false;
      if (pendingLoad && alive) { pendingLoad = false; void load(); }
    }
  }
  async function pinAsset(assetId: string) {
    try {
      const { detail } = await readDiscoveryView([assetId]);
      const row = detail?.rows.find(item => item.assetId === assetId);
      if (!row) throw new Error("比較対象の根拠を取得できません");
      await pinRow(row);
    } catch (cause) {
      if (cause instanceof DiscoveryGenerationChanged) { updating = true; unavailable = cause.message; }
      error = cause instanceof Error ? cause.message : "候補を追加できません";
    }
  }
  async function loadEpisodes() {
    if (cursorLoading) return;
    cursorLoading = true;
    try {
      const data = await requestDiscovery();
      episodes = mergeDiscoveryEpisodes(data.episodes, episodes);
      if (!historyPaged) cursor = data.nextCursor;
    } catch { error = "条件履歴を読み込めません"; }
    finally { cursorLoading = false; }
  }
  onMount(() => {
    alive = true;
    void Promise.all([readUserWorkspace(), fetch("/api/decisions", { cache: "no-store" }).then(async response => {
      if (!response.ok) throw new Error("判断履歴を読み込めません"); return await response.json() as DecisionHistory;
    })]).then(([saved, decisions]) => {
      if (!alive) return; workspace = saved; history = decisions; void load();
    }).catch(cause => { if (alive) { error = String(cause); void load(); } });
    const timer = setInterval(() => { if (document.visibilityState !== "hidden") void load(); }, 15_000);
    function compare(event: Event) {
      const detail = (event as CustomEvent<{ assetId: string }>).detail;
      if (!detail?.assetId) return;
      void pinAsset(detail.assetId);
    }
    window.addEventListener("watchdeck:compare", compare);
    return () => { alive = false; clearInterval(timer); window.removeEventListener("watchdeck:compare", compare); };
  });
  function rowFor(pin: ComparisonPin) {
    return pinnedRows.find(row => row.assetId === pin.target.id) ?? null;
  }
  function rowStatus(row: DiscoveryRow) {
    return unavailable ? "unavailable" : (pinnedDiscovery?.rows.some(item => item.assetId === row.assetId && item.raw.decisionAt === row.raw.decisionAt)
      ? pinnedDiscovery.status : discovery?.status ?? "unavailable");
  }
  function current(pin: ComparisonPin, row: DiscoveryRow | null) {
    return !!row && sameTarget(pin.target, discoveryTarget(row));
  }
  async function mutatePin(pin: ComparisonPin, enabled: boolean) {
    if (!workspace || busy) return;
    busy = true; error = null;
    try {
      const response = await fetch("/api/user-workspace", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "setPin", pin, enabled, expectedRevision: workspace.revision }) });
      if (!response.ok) throw new Error(response.status === 413 ? "比較は最大4件です。既存候補を外してください。"
        : response.status === 409 ? "保存内容または対象が更新されました。再読込して再確認してください。" : "比較候補を保存できません");
      workspace = await response.json(); await load();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : "比較候補を保存できません";
      try { workspace = await readUserWorkspace(); } catch { /* Preserve visible error. */ }
    } finally { busy = false; }
  }
  async function pinRow(row: DiscoveryRow) {
    const pin = comparisonPin(row);
    if (!pin) { error = "対象契約の対応を確認できません"; return; }
    if (pins.some(saved => favoriteKey(saved.target) === favoriteKey(pin.target))) {
      error = "比較候補に保存済みです。対象変更時は比較欄で再確認してください。"; return;
    }
    await mutatePin(pin, true);
  }
  function referenceLabel(key: string | null) {
    if (!key) return "未取得";
    const [venue, symbol] = key.split(":");
    return `${venue === "bybit" ? "Bybit" : venue} ${symbol ?? ""}`;
  }
  function number(value: number, kind: "price" | "amount" | "percent" | "raw") {
    if (kind === "price" || kind === "raw") return formatPrice(value);
    if (kind === "percent") return value.toFixed(2);
    const display = value.toLocaleString("ja-JP", { maximumFractionDigits: 2 });
    return value !== 0 && Number(display.replaceAll(",", "")) === 0 ? formatPrice(value) : display;
  }
  function ratio(value: number | null) { return value === null ? "未取得" : `${value.toFixed(2)}倍`; }
  function feature(value: RawFeatureValue | null | undefined, kind: "price" | "amount" | "percent" | "raw" = "raw") {
    return value?.status === "ready" && value.value !== null ? `${number(value.value, kind)} ${value.unit ?? "単位未確認"}`
      : `未取得 (${value?.reason ?? "missing"})`;
  }
  function time(value: number | null | undefined) { return value ? `${formatTimestamp(new Date(value).toISOString())} JST` : "時刻未取得"; }
  function direction(row: DiscoveryRow | DiscoverySummaryRow) {
    return row.direction === "turnover" ? row.state === "matched" ? "売買代金増加" : "価格方向 ±2% 内"
      : ({ up: "上昇", down: "下落", unknown: "方向未確認" })[row.direction];
  }
  function confirmation(row: DiscoveryRow | DiscoverySummaryRow) {
    return row.confirmation === "new" ? "新規成立" : row.confirmation === "initial_confirmation" ? "初回確認"
      : row.confirmation === "reconfirmation" ? "再確認" : row.confirmation === "continuing" ? "継続"
      : row.state === "not_matched" ? row.episodeId ? "条件解除" : "条件未成立" : "確認不能";
  }
  function changedSince(pin: ComparisonPin, row: DiscoveryRow | null) {
    const first = pin.snapshot.referenceClose as RawFeatureValue | undefined;
    const latest = row?.raw.referenceClose;
    return current(pin, row) && row && !["stale", "unavailable"].includes(rowStatus(row)) && first?.status === "ready" &&
      latest?.status === "ready" && first.unit === latest.unit && first.source === latest.source && first.value !== null && first.value > 0 && latest.value !== null
      ? `${((latest.value / first.value - 1) * 100).toFixed(2)}%` : "未取得 / 比較不能";
  }
  async function askNative(pin: ComparisonPin, row: DiscoveryRow, instrumentId: string, version: number) {
    if (updating) return;
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    nativeConfirm = { pin, row, instrumentId, version };
    await tick();
    confirmationRegion?.scrollIntoView({ block: "center" });
    confirmationRegion?.focus({ preventScroll: true });
  }
  function dismissConfirmation() {
    nativeConfirm = null; decisionFor = null;
    void tick().then(() => returnFocus?.focus());
  }
  function prepareDecision(pin: ComparisonPin, row: DiscoveryRow, action: "watch" | "skip") {
    if (updating) return;
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // Freeze the full evidence currently displayed, including status and the observation time.
    const evidenceResponse = pinnedDiscovery?.rows.some(item => item.assetId === row.assetId && item.raw.decisionAt === row.raw.decisionAt)
      ? pinnedDiscovery : null;
    decisionFor = { pin: structuredClone($state.snapshot(pin)), row: structuredClone($state.snapshot(row)), action, id: crypto.randomUUID(), snapshot: {
      row: structuredClone($state.snapshot(row)), displayedStatus: unavailable ? "unavailable" : evidenceResponse?.status ?? "unavailable",
      displayedAt: Date.now(), policy: structuredClone($state.snapshot(evidenceResponse?.policy)), generationId: evidenceResponse?.generationId,
      decisionAt: evidenceResponse?.decisionAt, rankingCutoff: evidenceResponse?.rankingCutoff
    } };
    reason = ""; error = null;
    void tick().then(() => { reasonInput?.scrollIntoView({ block: "center" }); reasonInput?.focus({ preventScroll: true }); });
  }
  async function saveDecision() {
    if (!decisionFor || !history || !reason.trim() || busy || updating) return;
    busy = true; error = null;
    const input: DecisionInput = { id: decisionFor.id, action: decisionFor.action, reason: reason.trim(),
      target: decisionFor.pin.target, episodeId: decisionFor.row.episodeId!, snapshot: decisionFor.snapshot };
    try {
      const response = await fetch("/api/decisions", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision: input, expectedRevision: history.revision }) });
      if (!response.ok) throw new Error(response.status === 413 ? "判断履歴の保存上限です。履歴は保持し、新規保存を拒否しました。"
        : response.status === 409 ? "別の画面で判断履歴が更新されました。内容を再確認して保存してください。" : "判断を保存できません。同じ操作を再試行できます。");
      history = await response.json(); reason = ""; dismissConfirmation();
    } catch (cause) {
      error = cause instanceof Error ? cause.message : "判断を保存できません";
      try { const response = await fetch("/api/decisions", { cache: "no-store" }); if (response.ok) history = await response.json(); } catch { /* Keep explicit error. */ }
    } finally { busy = false; }
  }
  async function moreEpisodes() {
    if (!cursor || cursorLoading) return; cursorLoading = true;
    try { const data = await requestDiscovery(new URLSearchParams({ cursor })); episodes = mergeDiscoveryEpisodes(data.episodes, episodes); historyPaged = true; cursor = data.nextCursor; }
    catch { error = "条件履歴の続きを読み込めません"; } finally { cursorLoading = false; }
  }
  async function confirmNative() {
    if (!nativeConfirm || updating) return;
    const { pin, instrumentId, version } = nativeConfirm;
    try {
      const latest = await requestDiscovery(new URLSearchParams({ assetId: pin.target.id,
        generationId: pinnedDiscovery?.generationId ?? "" }));
      const row = latest.rows.find(item => item.assetId === pin.target.id);
      if (latest.status === "stale" || latest.status === "unavailable" || !row || !current(pin, row) ||
          !row.originals.some(item => item.instrumentId === instrumentId && item.versionId === version && item.current)) {
        throw new Error("対象または根拠が更新されました。実Venueを再確認してください。");
      }
      const marketResponse = await fetch("/api/market-data", { cache: "no-store" });
      if (!marketResponse.ok) throw new Error("実Venueの現在の契約を確認できません");
      const market = await marketResponse.json() as MarketArtifactBundle;
      const native = row.native.find(item => item.instrumentId === instrumentId && item.versionId === version);
      const matches = market.universe.items.filter(item => item.venueInstrumentId === instrumentId && item.active &&
        item.venueInstrumentVersionId === version && item.sourceSymbol === native?.sourceSymbol && item.venue === native?.venue);
      if (!nativeUniverseFresh(market.universe, Date.now()) || matches.length !== 1 || !matches[0].groupId) {
        throw new Error("実Venueの対象・鮮度・対応を再確認してください");
      }
      if (updating) throw new DiscoveryGenerationChanged();
      const response = await fetch("/api/selection", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "select", groupId: matches[0].groupId, venueInstrumentId: instrumentId,
          venueInstrumentVersionId: version }) });
      if (!response.ok) throw new Error("実Venueの選択監視を切り替えられませんでした");
      nativeConfirm = null;
      await goto(`/?mode=native&instrument=${encodeURIComponent(instrumentId)}&version=${version}#native-detail`);
    } catch (cause) {
      if (cause instanceof DiscoveryGenerationChanged) { updating = true; unavailable = cause.message; void load(); }
      error = cause instanceof Error ? cause.message : "実Venueへ移動できません";
    }
  }
</script>

{#snippet metric(value: RawFeatureValue | null | undefined, kind: "price" | "amount" | "percent" | "raw" = "raw")}
  <span>{feature(value, kind)}</span>
  {#if value}<details class="metric-evidence"><summary>根拠</summary><small class="metric-source">source: {value.source} · 観測 {time(value.observedAt)} · 窓 {time(value.startAt)} → {time(value.endAt)} · 品質 {value.status} {value.reason ?? ""}</small></details>{/if}
{/snippet}

<section class="discovery" aria-label="候補比較と判断" data-testid="discovery-workflow">
  <header><h2>候補比較・判断 <span>{pins.length}/4</span></h2><p>固定監視: 15分売買代金が昨日・一昨日の両方の3倍以上 · 方向 ±2%。ブラウザの強調設定とは独立。</p></header>
  <p class="muted">条件履歴はAttention稼働中に保存されます。初回確認・再確認は成立の開始時刻を意味しません。ブラウザを閉じても判断記録と比較候補を保持します。</p>
  {#if unavailable}<p class="warning" role="status">{unavailable}。保存候補は保持しています。</p>{:else if discovery?.status === "stale"}<p class="warning" role="status">候補データが古くなっています。表示値は以前の観測です。</p>{/if}
  {#if error}<p class="warning" role="alert">{error}</p>{/if}
  <div class="candidate-list" aria-label="固定条件の成立候補">
    {#each candidates as row (row.assetId)}
      <button type="button" disabled={busy || updating || !workspace || !discoveryTarget(row) || pins.some(pin => pin.target.id === row.assetId)} onclick={() => pinAsset(row.assetId)}>
        {row.asset} · {direction(row)} · {confirmation(row)} · 比較へ
      </button>
    {:else}<p class="muted">{discovery ? "現在の成立候補なし / 不足情報は未取得として扱います。" : "候補を取得しています。"}</p>{/each}
  </div>
  <div class="comparison-grid">
    {#each pins as pin (favoriteKey(pin.target))}
      {@const row = rowFor(pin)}
      {@const identityCurrent = current(pin, row)}
      <article class="comparison" data-testid="comparison-card" data-target={pin.target.id}>
        <header><h3>{String(pin.snapshot.asset ?? pin.target.id)}</h3><button type="button" disabled={busy} onclick={() => mutatePin(pin, false)} aria-label={`${pin.target.id}を比較から外す`}>比較から外す</button></header>
        <details class="target"><summary>保存対象: {pin.target.kind === "reference" ? referenceLabel(pin.target.referenceKey) : `${pin.target.id} v${pin.target.version}`}</summary><p>{pin.target.kind === "reference" ? pin.target.referenceKey : `${pin.target.id} v${pin.target.version}`}</p></details>
        <p class="muted">比較へ追加: {time(pin.discoveredAt)} · 比較追加後の参照価格変化: {changedSince(pin, row)}</p>
        {#if !identityCurrent}<p class="warning">要再確認: 対応する元契約または参照市場が変更・欠測です。保存対象を保持しています。比較から外し、現在の対象を確認して追加してください。</p>{/if}
        {#if row && identityCurrent}
          <p>{confirmation(row)} · {direction(row)} {#if row.episodeId && episodeSkipped(history, row.episodeId)}· この成立は見送り済み{/if}</p>
          <p class="muted">固定監視の条件: 両日3倍以上 {#if row.reason}· {row.reason}{/if} · {time(row.raw.decisionAt)} · {row.raw.identityStatus} · 根拠品質: {rowStatus(row)}</p>
          <div class="reference">
            <h4>参照市場: {referenceLabel(row.referenceKey)}</h4>
            <p class="muted">15分窓の終了: {time(row.raw.referenceReturn15M.endAt)}</p>
            <dl><dt>参照価格</dt><dd>{@render metric(row.raw.referenceClose, "price")}</dd><dt>15分騰落</dt><dd>{@render metric(row.raw.referenceReturn15M, "percent")}</dd>
              <dt>15分売買代金</dt><dd>{@render metric(row.raw.referenceTurnover15M, "amount")}</dd>
              <dt>昨日 / 一昨日の同時間比</dt><dd>{ratio(row.turnoverComparison.previousDayRatio.value)} / {ratio(row.turnoverComparison.twoDaysAgoRatio.value)}</dd></dl>
          </div>
          {#each row.native as native (`${native.instrumentId}:${native.versionId}`)}
            <details class="native"><summary>実Venue: {native.instrumentId} v{native.versionId} · {native.quality}</summary>
              <p class="muted">観測: {time(native.markPrice.observedAt)}</p>
              <dl><dt>Mark</dt><dd>{@render metric(native.markPrice, "price")}</dd><dt>15分騰落</dt><dd>{@render metric(native.returnPct["15m"], "percent")}</dd>
                <dt>Funding raw / 1時間</dt><dd>{@render metric(native.fundingRateRaw)} / {@render metric(native.fundingRatePerHour)}</dd>
                <dt>Funding間隔</dt><dd>{native.fundingIntervalSeconds ?? "未取得"} 秒</dd>
                <dt>OI raw / base / notional</dt><dd>{@render metric(native.openInterestRaw, "amount")} / {@render metric(native.openInterestBase, "amount")} / {@render metric(native.openInterestNotional, "amount")}</dd>
                <dt>15分OI変化</dt><dd>{@render metric(native.oiChange["15m"], "percent")}</dd></dl>
              <details><summary>実Venueの根拠</summary><p class="muted">source: {native.markPrice.source} · source時刻: {time(native.markPrice.observations[0]?.sourceAt)} · {native.qualityReasons.join(" · ")}</p></details>
            </details>
            <button class="native-action" type="button" disabled={updating || ["stale", "unavailable"].includes(rowStatus(row)) || !row.originals.some(item => item.current && item.instrumentId === native.instrumentId && item.versionId === native.versionId)} onclick={() => askNative(pin, row, native.instrumentId, native.versionId)}>この実Venueを確認<span class="muted"> · {native.venue} {native.sourceSymbol}</span></button>
          {/each}
          <div class="actions"><button type="button" disabled={busy || updating || !history || !row.episodeId} onclick={() => prepareDecision(pin, row, "watch")}>監視を記録</button><button type="button" disabled={busy || updating || !history || !row.episodeId} onclick={() => prepareDecision(pin, row, "skip")}>この成立を見送り</button></div>
        {:else}<p>現在の根拠は未取得です。追加時の対象・根拠を保持しています。</p><details><summary>追加時の根拠</summary><pre>{JSON.stringify(pin.snapshot, null, 2)}</pre></details>{/if}
      </article>
    {:else}<p class="muted">成立候補やランキングの「比較へ」から最大4件を追加してください。追加だけでは実Venueのselectionを変更しません。</p>{/each}
  </div>
  {#if nativeConfirm}
    <div class="confirmation" bind:this={confirmationRegion} tabindex="-1" role="region" aria-label="実Venueへの移動確認"><p>{nativeConfirm.instrumentId} v{nativeConfirm.version} のnativeデータへ移動します。既存の選択監視をこの契約へ切り替えます。</p><button type="button" disabled={updating} onclick={confirmNative}>確認して実Venueへ移動</button><button type="button" onclick={dismissConfirmation}>キャンセル</button></div>
  {/if}
  {#if decisionFor}
    <form class="confirmation" onsubmit={event => { event.preventDefault(); void saveDecision(); }} aria-label="判断を保存">
      <p>{decisionFor.pin.target.id} · {decisionFor.action === "watch" ? "監視" : "見送り"} · 成立 {decisionFor.row.episodeId}</p><p class="muted">根拠を固定: {time(decisionFor.row.raw.decisionAt)}。この表示snapshotを履歴へ保存します。</p>
      <label>判断理由<textarea bind:this={reasonInput} bind:value={reason} maxlength="2000" required></textarea></label><button type="submit" disabled={busy || updating || !reason.trim()}>判断を保存</button><button type="button" onclick={dismissConfirmation}>キャンセル</button>
    </form>
  {/if}
  <details ontoggle={event => { if (event.currentTarget.open) void loadEpisodes(); }}><summary>条件履歴 ({episodes.length}) · 保持開始 {time(discovery?.historyAvailableFrom)} · 終了履歴7日 / 最大10,000件</summary>
    {#each episodes as episode (episode.id)}<p>{episode.asset} · {episode.startKind === "new" ? "新規成立" : episode.startKind === "reconfirmation" ? "再確認" : "初回確認"} · {episode.state} · 初回観測 {time(episode.firstObservedAt)} · 最終確認 {time(episode.lastConfirmedAt)} · {episode.consecutiveConfirmations}回 · 観測継続 {formatFinite(episode.observedDurationMs / 60000, 1)}分 · {episode.endReason ?? ""}</p>{/each}
    {#if cursor}<button type="button" disabled={cursorLoading} onclick={moreEpisodes}>条件履歴をさらに読む</button>{/if}
  </details>
  <details data-testid="manual-history"><summary>判断履歴 ({history?.decisions.length ?? 0}) · 自動削除なし</summary>
    <label>判断履歴を検索<input bind:value={historyFilter} placeholder="対象・理由" /></label>
    {#each [...(history?.decisions ?? [])].reverse().filter(entry => `${entry.target.id} ${entry.reason}`.includes(historyFilter)) as entry (entry.id)}
      <details><summary>{entry.target.id} · {entry.action === "watch" ? "監視" : "見送り"} · {formatTimestamp(entry.recordedAt)} JST · {entry.reason}</summary><p>成立: {entry.episodeId} · 保存対象: {JSON.stringify(entry.target)}</p><pre>{JSON.stringify(entry.snapshot, null, 2)}</pre></details>
    {/each}
    <p class="muted">1000件または16MiBで新規保存を拒否します。自動条件履歴の期限後もこのsnapshotを読めます。</p>
  </details>
</section>

<style>
  .discovery { max-width:1900px; margin:var(--space-md) auto; padding:var(--space-md); border:1px solid var(--line); background:var(--surface); color:var(--text); }
  header { display:flex; justify-content:space-between; align-items:center; gap:var(--space-sm); flex-wrap:wrap; }
  h2,h3,h4,p { margin:0; } h2 { font-size:var(--type-heading-md-size); } h3 { font-size:var(--type-title-lg-size); } h4 { font-size:var(--type-body-md-size); }
  p { margin-top:var(--space-xs); font-size:var(--type-body-sm-size); line-height:1.5; overflow-wrap:anywhere; }
  .metric-source { display:block; color:var(--muted); font-size:var(--type-body-sm-size); overflow-wrap:anywhere; }
  .metric-evidence { margin-top:0; } .metric-evidence summary { color:var(--muted); font-size:var(--type-body-sm-size); }
  .native-action { margin-top:var(--space-xs); }
  .muted { color:var(--muted); } .warning { color:var(--warning); } .candidate-list,.actions { display:flex; gap:var(--space-sm); flex-wrap:wrap; margin:var(--space-sm) 0; }
  button,input,textarea { font:inherit; color:var(--text); background:var(--panel-solid); border:1px solid var(--line); border-radius:var(--radius-control,2px); min-height:var(--control-height-dense,24px); padding:var(--space-xs) var(--space-sm); }
  button { cursor:pointer; } button:disabled { opacity:.5; cursor:default; } button:focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
  .comparison-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,310px),1fr)); gap:var(--space-md); }
  .comparison { padding:var(--space-sm); border:1px solid var(--line); min-width:0; } .target { overflow-wrap:anywhere; }
  .reference { border-left:2px solid var(--line-strong); padding-left:var(--space-sm); margin:var(--space-sm) 0; } .native { margin:var(--space-sm) 0; }
  dl { display:grid; grid-template-columns:minmax(5rem,.7fr) minmax(0,1fr); gap:var(--space-xs); margin:var(--space-sm) 0; font-size:var(--type-body-sm-size); } dt { color:var(--muted); } dd { margin:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
  details { margin-top:var(--space-sm); font-size:var(--type-body-sm-size); } summary { cursor:pointer; overflow-wrap:anywhere; line-height:1.6; }
  pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:24rem; overflow:auto; }
  .confirmation { border:1px solid var(--warning-border); margin:var(--space-sm) 0; padding:var(--space-md); } .confirmation button { margin-top:var(--space-sm); }
  label { display:flex; flex-direction:column; gap:var(--space-xs); margin-top:var(--space-sm); } textarea { width:100%; box-sizing:border-box; min-height:5rem; }
  @media(max-width:48rem) { .discovery { margin:var(--space-sm); } button { min-height:var(--control-height-touch,44px); } .comparison-grid { grid-template-columns:1fr; } }
</style>
