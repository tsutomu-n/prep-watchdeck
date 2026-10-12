<script lang="ts">
  import { onMount, tick } from "svelte";
  import { goto, afterNavigate } from "$app/navigation";
  import type { DiscoveryResponse, DiscoveryRow, RawFeatureValue, DiscoveryEpisode } from "$lib/generated/discovery-response";
  import type { DiscoverySummary, DiscoverySummaryRow } from "$lib/generated/discovery-summary";
  import { DiscoveryGenerationChanged, readDiscoveryView, requestDiscovery } from "$lib/discovery/client";
  import { DECISION_DRAFT_KEY, decisionDraftInput, parseDecisionDraft, type DecisionDraft } from "$lib/discovery/decision-draft";
  import type { ComparisonPin, UserWorkspace } from "$lib/server/user-workspace-repository";
  import type { DecisionHistory } from "$lib/market/decisions";
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
  let workspaceError = $state<string | null>(null);
  let historyError = $state<string | null>(null);
  let workspaceLoading = $state(false);
  let historyLoading = $state(false);
  let workspaceRead = 0;
  let historyRead = 0;
  let error = $state<string | null>(null);
  let unavailable = $state<string | null>(null);
  let busy = $state(false);
  let nativeConfirm = $state<{ pin: ComparisonPin; row: DiscoveryRow; instrumentId: string; version: number } | null>(null);
  let decisionFor = $state<DecisionDraft | null>(null);
  let draftWarning = $state<string | null>(null);
  let draftUnreadable = $state(false);
  let decisionBlocked = $derived(decisionBlockReason());
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
  let panel = $state<HTMLDialogElement | null>(null);
  let panelOpen = $state(false);
  let closeButton = $state<HTMLButtonElement | null>(null);
  let entryButton = $state<HTMLButtonElement | null>(null);
  let candidateQuery = $state("");
  let candidatePage = $state(1);
  let filteredCandidates = $derived(candidates.filter(row => row.asset.toLocaleLowerCase().includes(candidateQuery.trim().toLocaleLowerCase())));
  let candidatePages = $derived(Math.max(1, Math.ceil(filteredCandidates.length / 10)));
  let visibleCandidates = $derived(filteredCandidates.slice((candidatePage - 1) * 10, candidatePage * 10));
  let notice = $state<{ message: string; assetId: string } | null>(null);
  let panelReturnFocus: HTMLElement | null = null;
  let scrollPosition = { x: 0, y: 0 };
  let bodyStyles: { position: string; top: string; left: string; width: string; overflow: string } | null = null;
  let summaryStatus = $derived(updating ? "候補の更新待ち" : unavailable ? "候補機能を利用できません"
    : discovery?.status === "stale" ? "前回の観測 · 更新停止"
    : discovery?.status === "partial" ? "一部確認不能"
    : workspaceError ? "保存候補を確認できません" : historyError ? "判断履歴を確認できません"
    : !discovery ? "候補を取得中" : null);

  $effect(() => { if (candidatePage > candidatePages) candidatePage = candidatePages; });

  async function openPanel(assetId?: string) {
    if (!panel || panel.open) return;
    panelReturnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : entryButton;
    scrollPosition = { x: window.scrollX, y: window.scrollY };
    const style = document.body.style;
    bodyStyles = { position: style.position, top: style.top, left: style.left, width: style.width, overflow: style.overflow };
    style.position = "fixed"; style.top = `-${scrollPosition.y}px`; style.left = `-${scrollPosition.x}px`;
    style.width = "100%"; style.overflow = "hidden";
    panel.showModal(); panelOpen = true;
    await tick();
    if (!panel.open) return;
    const card = assetId ? Array.from(panel.querySelectorAll<HTMLElement>("[data-target]"))
      .find(item => item.dataset.target === assetId) : null;
    if (card) { card.scrollIntoView({ block: "nearest" }); card.focus({ preventScroll: true }); }
    else closeButton?.focus({ preventScroll: true });
  }
  function trapPanelFocus(event: KeyboardEvent) {
    if (event.key === "Escape") { event.preventDefault(); closePanel(); return; }
    if (event.key !== "Tab" || !panel) return;
    const controls = Array.from(panel.querySelectorAll<HTMLElement>(
      'button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])'
    )).filter(item => !item.matches(":disabled") && item.checkVisibility() && item.getClientRects().length > 0);
    const first = controls[0]; const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  }
  function restorePage() {
    if (!bodyStyles) return;
    Object.assign(document.body.style, bodyStyles); bodyStyles = null;
    window.scrollTo({ left: scrollPosition.x, top: scrollPosition.y, behavior: "instant" });
  }
  function closePanel(restoreFocus = true) {
    if (!panel?.open) return;
    panel.close(); panelOpen = false; nativeConfirm = null;
    restorePage();
    if (restoreFocus) {
      const trigger = panelReturnFocus;
      void tick().then(() => {
        if (!panelOpen) (trigger?.isConnected ? trigger : entryButton)?.focus({ preventScroll: true });
      });
    }
  }
  afterNavigate(() => closePanel(false));

  let coverage = $derived.by(() => {
    if (!discovery || discovery.status === "unavailable") return null;
    const counts = { total: discovery.rows.length, matched: 0, notMatched: 0,
      identityPending: 0, comparisonUnavailable: 0, otherPending: 0 };
    for (const row of discovery.rows) {
      if (row.state === "matched") counts.matched++;
      else if (row.state === "not_matched") counts.notMatched++;
      else if (row.reason === "identity_ineligible") counts.identityPending++;
      else if (row.reason === "comparison_unavailable") counts.comparisonUnavailable++;
      else counts.otherPending++;
    }
    return counts;
  });

  function rememberDraft() {
    if (!decisionFor) return;
    try { sessionStorage.setItem(DECISION_DRAFT_KEY, JSON.stringify($state.snapshot(decisionFor))); draftWarning = null; }
    catch { draftWarning = "下書きをこのタブへ保存できません。この画面を閉じると失われる可能性があります。"; }
  }
  function restoreDraft() {
    let stored: string | null;
    try { stored = sessionStorage.getItem(DECISION_DRAFT_KEY); }
    catch {
      draftWarning = "タブ保存を利用できません。下書きは画面内だけで保持し、この画面を閉じると失われる可能性があります。";
      return;
    }
    if (!stored) return;
    try {
      const draft = parseDecisionDraft(JSON.parse(stored));
      if (!draft) throw new Error("invalid draft");
      decisionFor = draft;
    } catch {
      draftUnreadable = true;
      draftWarning = "保存済み下書きを復元できません。保存内容は保持しています。新しい判断には明示的な破棄が必要です。";
    }
  }
  function discardDraft() {
    if (busy) return;
    draftWarning = null;
    try { sessionStorage.removeItem(DECISION_DRAFT_KEY); }
    catch { draftWarning = "画面内の下書きは解除しましたが、タブ保存から削除できません。再読込すると戻る可能性があります。"; }
    decisionFor = null; draftUnreadable = false;
    void tick().then(() => returnFocus?.focus());
  }
  function updateReason(value: string) {
    if (!decisionFor || decisionFor.submitted || busy) return;
    decisionFor.reason = value;
    rememberDraft();
  }
  function decisionBlockReason() {
    if (!decisionFor) return null;
    if (updating) return "候補の更新待ちです。元の下書きと根拠を保持しています。";
    if (!history || historyError || historyLoading) return "判断履歴が未確認のため保存できません。下書きは保持しています。";
    if (!workspace || workspaceError || workspaceLoading) return "比較候補が未確認のため保存できません。下書きは保持しています。";
    const pin = pins.find(item => sameTarget(item.target, decisionFor!.pin.target));
    const row = pin ? rowFor(pin) : null;
    if (!pin || row && !current(pin, row)) return "保存対象が変更・削除されています。元の対象と下書きを保持しています。";
    if (!row || unavailable) return "現在の対象・根拠を確認できません。元の下書きを保持しています。";
    if (row.episodeId !== decisionFor.row.episodeId) return "成立が変更されています。元の成立と下書きを保持しています。";
    return null;
  }
  function settleDraft() {
    if (!decisionFor?.submitted || !history) return false;
    const entry = history.decisions.find(item => item.id === decisionFor!.id);
    if (!entry) return false;
    const { recordedAt: _recordedAt, ...saved } = entry;
    if (JSON.stringify(saved) !== JSON.stringify(decisionDraftInput(decisionFor))) {
      error = "同じ判断idに異なる保存内容があります。下書きを保持しています。";
      return false;
    }
    discardDraft();
    return true;
  }
  async function loadWorkspace() {
    if (workspaceLoading || !alive) return;
    const read = ++workspaceRead;
    workspaceLoading = true;
    try {
      const saved = await readUserWorkspace();
      if (!alive || read !== workspaceRead) return;
      workspace = saved; workspaceError = null; void load();
    } catch { if (alive && read === workspaceRead) workspaceError = "比較候補を読み込めません。保存内容は保持しています。"; }
    finally { if (alive && read === workspaceRead) workspaceLoading = false; }
  }
  async function loadHistory() {
    if (historyLoading || !alive) return;
    const read = ++historyRead;
    historyLoading = true;
    try {
      const response = await fetch("/api/decisions", { cache: "no-store" });
      if (!response.ok) throw new Error("history unavailable");
      const saved = await response.json() as DecisionHistory;
      if (!alive || read !== historyRead) return;
      history = saved; historyError = null;
      if (!busy && settleDraft()) error = null;
    } catch { if (alive && read === historyRead) { history = null; historyError = "判断履歴を読み込めません。見送り適用は未確認で、判断保存を停止しています。"; } }
    finally { if (alive && read === historyRead) historyLoading = false; }
  }

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
    error = null; notice = null;
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
    restoreDraft();
    void loadWorkspace(); void loadHistory(); void load();
    const timer = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      void load();
      if (!busy) {
        if (workspaceError) void loadWorkspace();
        if (historyError) void loadHistory();
      }
    }, 15_000);
    function compare(event: Event) {
      const detail = (event as CustomEvent<{ assetId: string }>).detail;
      if (!detail?.assetId) return;
      void pinAsset(detail.assetId);
    }
    window.addEventListener("watchdeck:compare", compare);
    return () => { alive = false; workspaceRead++; historyRead++; clearInterval(timer); window.removeEventListener("watchdeck:compare", compare); restorePage(); };
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
    if (!workspace || workspaceLoading || workspaceError || busy) return false;
    busy = true; error = null; notice = null;
    try {
      const response = await fetch("/api/user-workspace", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ action: "setPin", pin, enabled, expectedRevision: workspace.revision }) });
      if (!response.ok) throw new Error(response.status === 413 ? "比較は最大4件です。既存候補を外してください。"
        : response.status === 409 ? "保存内容または対象が更新されました。再読込して再確認してください。" : "比較候補を保存できません");
      const saved = await response.json();
      if (!alive) return;
      workspace = saved; await load();
      return true;
    } catch (cause) {
      error = cause instanceof Error ? cause.message : "比較候補を保存できません";
      if (alive) await loadWorkspace();
      return false;
    } finally { if (alive) busy = false; }
  }
  async function pinRow(row: DiscoveryRow) {
    error = null; notice = null;
    if (!workspace || workspaceLoading || workspaceError) { error = "保存候補を確認できません。比較パネルから再取得してください。"; return; }
    if (busy) { error = "比較候補を保存中です。完了後に追加してください。"; return; }
    const pin = comparisonPin(row);
    if (!pin) { error = "対象契約の対応を確認できません"; return; }
    if (pins.some(saved => favoriteKey(saved.target) === favoriteKey(pin.target))) {
      notice = { message: `${row.asset}は追加済みです。保存対象は比較欄で確認できます。`, assetId: row.assetId }; return;
    }
    if (await mutatePin(pin, true)) notice = { message: `${row.asset}を比較に追加しました`, assetId: row.assetId };
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
    if (updating || busy || decisionFor || draftUnreadable) return;
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    nativeConfirm = { pin, row, instrumentId, version };
    await tick();
    confirmationRegion?.scrollIntoView({ block: "center" });
    confirmationRegion?.focus({ preventScroll: true });
  }
  function dismissConfirmation() {
    nativeConfirm = null;
    void tick().then(() => returnFocus?.focus());
  }
  function prepareDecision(pin: ComparisonPin, row: DiscoveryRow, action: "watch" | "skip") {
    if (updating || busy || !history || historyError || decisionFor || draftUnreadable || nativeConfirm) return;
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // Freeze the full evidence currently displayed, including status and the observation time.
    const evidenceResponse = pinnedDiscovery?.rows.some(item => item.assetId === row.assetId && item.raw.decisionAt === row.raw.decisionAt)
      ? pinnedDiscovery : null;
    decisionFor = { pin: structuredClone($state.snapshot(pin)), row: structuredClone($state.snapshot(row)), action, id: crypto.randomUUID(), snapshot: {
      row: structuredClone($state.snapshot(row)), displayedStatus: unavailable ? "unavailable" : evidenceResponse?.status ?? "unavailable",
      displayedAt: Date.now(), policy: structuredClone($state.snapshot(evidenceResponse?.policy)), generationId: evidenceResponse?.generationId,
      decisionAt: evidenceResponse?.decisionAt, rankingCutoff: evidenceResponse?.rankingCutoff
    }, reason: "", submitted: false };
    rememberDraft(); error = null;
    void tick().then(() => { reasonInput?.scrollIntoView({ block: "center" }); reasonInput?.focus({ preventScroll: true }); });
  }
  async function saveDecision() {
    if (!decisionFor || !history || !decisionFor.reason.trim() || busy || decisionBlocked) return;
    busy = true; error = null;
    decisionFor.submitted = true;
    rememberDraft();
    const input = decisionDraftInput(decisionFor);
    try {
      const response = await fetch("/api/decisions", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ decision: input, expectedRevision: history.revision }) });
      if (!response.ok) throw new Error(response.status === 413 ? "判断履歴の保存上限です。履歴は保持し、新規保存を拒否しました。"
        : response.status === 409 ? "別の画面で判断履歴が更新されました。内容を再確認して保存してください。" : "判断を保存できません。同じ操作を再試行できます。");
      const saved = await response.json();
      if (!alive || decisionFor?.id !== input.id) return;
      history = saved; historyError = null;
      busy = false;
      if (!settleDraft()) error = "保存結果を確認できません。下書きは保持しています。同じ操作を再試行できます。";
    } catch (cause) {
      if (!alive) return;
      error = cause instanceof Error ? cause.message : "判断を保存できません";
      await loadHistory();
      busy = false;
      if (settleDraft()) error = null;
    } finally { if (alive) busy = false; }
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
      closePanel(false);
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
  <div class="entry-row">
    <button type="button" bind:this={entryButton} aria-haspopup="dialog" aria-controls="comparison-panel" aria-expanded={panelOpen} onclick={() => openPanel()}>
      候補・比較 <span>保存{workspace ? `${pins.length}/4` : "未取得"}</span>
    </button>
    {#if summaryStatus}<p class="warning" role="status">{summaryStatus}</p>{/if}
  </div>
  {#if notice || error}
    <div class="feedback" data-testid="comparison-feedback" hidden={panelOpen}>
      {#if error}<p class="warning" role="alert">{error}</p>{:else if notice}<p role="status">{notice.message}</p>{/if}
      {#if notice}<button type="button" onclick={() => openPanel(notice?.assetId)}>比較を見る</button>{/if}
      <button type="button" onclick={() => { notice = null; error = null; }} aria-label="比較の通知を閉じる">閉じる</button>
    </div>
  {/if}
  <dialog id="comparison-panel" bind:this={panel} aria-labelledby="comparison-title" onkeydown={trapPanelFocus} oncancel={event => { event.preventDefault(); closePanel(); }}>
    <header class="panel-header"><h2 id="comparison-title">候補・比較</h2><button type="button" bind:this={closeButton} onclick={() => closePanel()}>一覧に戻る</button></header>
    <div class="panel-content">
  {#if unavailable}<p class="warning" role="status">{unavailable}。保存候補は保持しています。</p>{:else if discovery?.status === "stale"}<p class="warning" role="status">候補データが古くなっています。表示値は以前の観測です。</p>{/if}
  {#if workspaceError}<p class="warning" role="alert">{workspaceError}</p><button type="button" disabled={busy || workspaceLoading} onclick={loadWorkspace}>比較候補を再取得</button>{/if}
  {#if historyError}<p class="warning" role="alert">{historyError}</p><button type="button" disabled={busy || historyLoading} onclick={loadHistory}>判断履歴を再取得</button>{:else if !history}<p class="muted">判断履歴を確認中です。見送り適用は未確認で、判断保存を停止しています。</p>{/if}
  {#if draftWarning}<p class="warning" role="status">{draftWarning}</p>{/if}
  {#if draftUnreadable}<button type="button" disabled={busy} onclick={discardDraft}>保存済み下書きを破棄</button>{/if}
  {#if error}<p class="warning" role="alert">{error}</p>{/if}
  {#if notice}<p role="status">{notice.message}</p>{/if}
  <h3>保存済み比較 {workspace ? `${pins.length}/4` : "未取得"}</h3>
  <div class="comparison-grid">
    {#each pins as pin (favoriteKey(pin.target))}
      {@const row = rowFor(pin)}
      {@const identityCurrent = current(pin, row)}
      <article class="comparison" data-testid="comparison-card" data-target={pin.target.id} tabindex="-1" aria-label={`${String(pin.snapshot.asset ?? pin.target.id)}の比較`}>
        <header><h3>{String(pin.snapshot.asset ?? pin.target.id)}</h3><button type="button" disabled={busy || workspaceLoading || !!workspaceError} onclick={() => mutatePin(pin, false)} aria-label={`${pin.target.id}を比較から外す`}>比較から外す</button></header>
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
            <button class="native-action" type="button" disabled={busy || !!decisionFor || draftUnreadable || updating || ["stale", "unavailable"].includes(rowStatus(row)) || !row.originals.some(item => item.current && item.instrumentId === native.instrumentId && item.versionId === native.versionId)} onclick={() => askNative(pin, row, native.instrumentId, native.versionId)}>この実Venueを確認<span class="muted"> · {native.venue} {native.sourceSymbol}</span></button>
            </details>
          {/each}
          <div class="actions"><button type="button" disabled={busy || updating || historyLoading || !!decisionFor || draftUnreadable || !!nativeConfirm || !history || !row.episodeId} onclick={() => prepareDecision(pin, row, "watch")}>監視を記録</button><button type="button" disabled={busy || updating || historyLoading || !!decisionFor || draftUnreadable || !!nativeConfirm || !history || !row.episodeId} onclick={() => prepareDecision(pin, row, "skip")}>この成立を見送り</button></div>
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
      <p class="muted">{draftWarning ? "判断下書きはこの画面で保持しています。" : "判断下書きをこのタブで保持しています。"}別の判断・実Venue確認へ切り替えるには、保存または明示的な破棄が必要です。</p>
      {#if decisionBlocked}<p class="warning" aria-live="polite">{decisionBlocked}</p>{/if}
      {#if decisionFor.submitted}<p class="muted">送信済みの内容を保持しています。保存結果が確認できるまで、同じ判断id・理由・根拠で再試行します。</p>{/if}
      <label>判断理由<textarea bind:this={reasonInput} value={decisionFor.reason} oninput={event => updateReason(event.currentTarget.value)} disabled={busy || decisionFor.submitted} maxlength="2000" required></textarea></label><button type="submit" disabled={busy || !!decisionBlocked || !decisionFor.reason.trim()}>判断を保存</button><button type="button" disabled={busy} onclick={discardDraft}>下書きを破棄</button>
    </form>
  {/if}
  <section class="candidates" aria-label="成立候補">
    <h3>成立候補 {discovery && !unavailable && discovery.status !== "unavailable" ? `${filteredCandidates.length}件${discovery.status === "stale" ? " · 前回観測" : ""}` : "件数未取得"}</h3>
    <label>候補の銘柄検索<input type="search" bind:value={candidateQuery} oninput={() => candidatePage = 1} placeholder="銘柄名で検索" /></label>
    <div class="candidate-list" aria-label="固定条件の成立候補">
      {#each visibleCandidates as row (row.assetId)}
        <button type="button" disabled={busy || updating || workspaceLoading || !!workspaceError || !workspace || !discoveryTarget(row) || pins.some(pin => pin.target.id === row.assetId)} onclick={() => pinAsset(row.assetId)}>
          {row.asset} · {direction(row)} · {confirmation(row)} · 比較へ
        </button>
      {:else}<p class="muted">{!discovery || unavailable || discovery.status === "unavailable" ? "候補を確認できません / 取得状況を確認してください。" : candidateQuery ? "検索に一致する候補なし" : "現在の成立候補なし / 不足情報は未取得として扱います。"}</p>{/each}
    </div>
    <nav class="pagination" aria-label="候補のページ切り替え">
      <button type="button" disabled={candidatePage <= 1} onclick={() => candidatePage--}>前の10件</button>
      <span>{candidatePage} / {candidatePages}</span>
      <button type="button" disabled={candidatePage >= candidatePages} onclick={() => candidatePage++}>次の10件</button>
    </nav>
  </section>
  <details><summary>固定監視の条件・取得状況</summary>
    <p>固定監視: 15分売買代金が昨日・一昨日の両方の3倍以上 · 方向 ±2%。ブラウザの強調設定とは独立。</p>
    <p class="muted">条件履歴はAttention稼働中に保存されます。初回確認・再確認は成立の開始時刻を意味しません。ブラウザを閉じても判断記録と比較候補を保持します。</p>
  {#if coverage}
    <section class="coverage" aria-label="固定条件の判定状況">
      <p><strong>{unavailable || updating || discovery?.status === "stale" ? "前回観測 · " : ""}条件判定済み {coverage.matched + coverage.notMatched} / {coverage.total}</strong> · 成立 {coverage.matched} · 不成立 {coverage.notMatched}</p>
      <p class="muted">対象確認待ち {coverage.identityPending} · 比較値確認不能 {coverage.comparisonUnavailable}{#if coverage.otherPending} · その他の確認待ち {coverage.otherPending}{/if}</p>
      {#if discovery?.status === "partial"}<p class="warning">一部の対象・条件履歴を確認できません。判定済みの行は個別に確認できます。</p>{/if}
      <p class="muted">条件判定は {time(discovery?.decisionAt)} の観測です。実Venueの鮮度は各比較欄で確認してください。</p>
    </section>
  {/if}
    <p class="muted">観測: {time(discovery?.decisionAt)} · 品質: {unavailable || updating ? "unavailable" : discovery?.status ?? "未取得"} · {discovery?.reason ?? ""}</p>
  </details>
  <details ontoggle={event => { if (event.currentTarget.open) void loadEpisodes(); }}><summary>条件履歴 ({episodes.length}) · 保持開始 {time(discovery?.historyAvailableFrom)} · 終了履歴7日 / 最大10,000件</summary>
    {#each episodes as episode (episode.id)}<p>{episode.asset} · {episode.startKind === "new" ? "新規成立" : episode.startKind === "reconfirmation" ? "再確認" : "初回確認"} · {episode.state} · 初回観測 {time(episode.firstObservedAt)} · 最終確認 {time(episode.lastConfirmedAt)} · {episode.consecutiveConfirmations}回 · 観測継続 {formatFinite(episode.observedDurationMs / 60000, 1)}分 · {episode.endReason ?? ""}</p>{/each}
    {#if cursor}<button type="button" disabled={cursorLoading} onclick={moreEpisodes}>条件履歴をさらに読む</button>{/if}
  </details>
  <details data-testid="manual-history"><summary>判断履歴 ({history ? history.decisions.length : "未確認"}) · 自動削除なし</summary>
    <label>判断履歴を検索<input bind:value={historyFilter} placeholder="対象・理由" /></label>
    {#each [...(history?.decisions ?? [])].reverse().filter(entry => `${entry.target.id} ${entry.reason}`.includes(historyFilter)) as entry (entry.id)}
      <details><summary>{entry.target.id} · {entry.action === "watch" ? "監視" : "見送り"} · {formatTimestamp(entry.recordedAt)} JST · {entry.reason}</summary><p>成立: {entry.episodeId} · 保存対象: {JSON.stringify(entry.target)}</p><pre>{JSON.stringify(entry.snapshot, null, 2)}</pre></details>
    {/each}
    <p class="muted">1000件または16MiBで新規保存を拒否します。自動条件履歴の期限後もこのsnapshotを読めます。</p>
  </details>
    </div>
  </dialog>
</section>

<style>
  .coverage { border-left:2px solid var(--line-strong); padding-left:var(--space-sm); margin:var(--space-sm) 0; overflow-wrap:anywhere; }
  .discovery { max-width:1900px; margin:0 auto; padding:var(--space-xs) var(--space-page); color:var(--text); }
  .entry-row { display:flex; align-items:center; flex-wrap:wrap; gap:var(--space-sm); }
  .entry-row p { margin:0; }
  dialog { position:fixed; inset:0 0 0 auto; box-sizing:border-box; width:min(720px,100vw); height:100dvh; max-width:100vw; max-height:100dvh; margin:0; padding:0; border:0; border-left:1px solid var(--line); background:var(--surface); color:var(--text); overflow:hidden; }
  dialog[open] { display:flex; flex-direction:column; }
  dialog::backdrop { background:rgb(0 0 0 / .65); }
  .panel-header { flex-shrink:0; padding:var(--space-sm) var(--space-md); border-bottom:1px solid var(--line); background:var(--panel-solid); }
  .panel-content { min-height:0; overflow-y:auto; overscroll-behavior:contain; padding:var(--space-md); }
  .feedback { position:fixed; z-index:10; bottom:max(var(--space-md),env(safe-area-inset-bottom)); left:50%; transform:translateX(-50%); width:max-content; max-width:calc(100vw - 2rem); box-sizing:border-box; display:flex; align-items:center; flex-wrap:wrap; gap:var(--space-sm); padding:var(--space-sm); border:1px solid var(--line-strong); background:var(--panel-solid); }
  .feedback[hidden] { display:none; }
  .feedback p { flex:1 1 12rem; margin:0; }
  .candidates { margin:var(--space-md) 0; padding-top:var(--space-md); border-top:1px solid var(--line); }
  .pagination { display:flex; align-items:center; justify-content:space-between; gap:var(--space-sm); }
  .candidate-list button { width:100%; text-align:left; overflow-wrap:anywhere; }
  input { min-width:0; width:100%; box-sizing:border-box; }
  header { display:flex; justify-content:space-between; align-items:center; gap:var(--space-sm); flex-wrap:wrap; }
  h2,h3,h4,p { margin:0; } h2 { font-size:var(--type-heading-md-size); } h3 { font-size:var(--type-title-lg-size); } h4 { font-size:var(--type-body-md-size); }
  p { margin-top:var(--space-xs); font-size:var(--type-body-sm-size); line-height:1.5; overflow-wrap:anywhere; }
  .metric-source { display:block; color:var(--muted); font-size:var(--type-body-sm-size); overflow-wrap:anywhere; }
  .metric-evidence { margin-top:0; } .metric-evidence summary { color:var(--muted); font-size:var(--type-body-sm-size); }
  .native-action { margin-top:var(--space-xs); }
  .muted { color:var(--muted); } .warning { color:var(--warning); } .candidate-list,.actions { display:flex; gap:var(--space-sm); flex-wrap:wrap; margin:var(--space-sm) 0; }
  button,input,textarea { font:inherit; color:var(--text); background:var(--panel-solid); border:1px solid var(--line); border-radius:var(--radius-control,2px); min-height:44px; padding:var(--space-xs) var(--space-sm); }
  button { cursor:pointer; } button:disabled { opacity:.5; cursor:default; } button:focus-visible,input:focus-visible,textarea:focus-visible,summary:focus-visible,.comparison:focus-visible { outline:2px solid var(--focus); outline-offset:2px; }
  .comparison-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:var(--space-md); }
  .comparison { padding:var(--space-sm); border:1px solid var(--line); min-width:0; } .target { overflow-wrap:anywhere; }
  .reference { border-left:2px solid var(--line-strong); padding-left:var(--space-sm); margin:var(--space-sm) 0; } .native { margin:var(--space-sm) 0; }
  dl { display:grid; grid-template-columns:minmax(5rem,.7fr) minmax(0,1fr); gap:var(--space-xs); margin:var(--space-sm) 0; font-size:var(--type-body-sm-size); } dt { color:var(--muted); } dd { margin:0; font-variant-numeric:tabular-nums; overflow-wrap:anywhere; }
  details { margin-top:var(--space-sm); font-size:var(--type-body-sm-size); } summary { cursor:pointer; overflow-wrap:anywhere; line-height:1.6; }
  pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:24rem; overflow:auto; }
  .confirmation { border:1px solid var(--warning-border); margin:var(--space-sm) 0; padding:var(--space-md); } .confirmation button { margin-top:var(--space-sm); }
  label { display:flex; flex-direction:column; gap:var(--space-xs); margin-top:var(--space-sm); } textarea { width:100%; box-sizing:border-box; min-height:5rem; }
  @media(max-width:48rem) { dialog { width:100vw; border:0; } .panel-header { padding-top:max(var(--space-sm),env(safe-area-inset-top)); } .panel-content { padding-bottom:max(var(--space-md),env(safe-area-inset-bottom)); } .comparison-grid { grid-template-columns:1fr; } }
</style>
