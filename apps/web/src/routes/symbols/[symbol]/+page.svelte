<script lang="ts">
  import MarketChart from "$lib/MarketChart.svelte";
  import {
    filterPastNotesBySymbol,
    isPastNote,
    type PastNote
  } from "$lib/past-note/past-note";
  import { savePastNoteRecord } from "$lib/past-note/past-note-client";
  import { rankingPosition } from "$lib/market/rankings";
  import { movementSignals, range24h } from "$lib/market/row-analysis";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import SymbolHeader from "$lib/components/symbol/SymbolHeader.svelte";
  import SymbolMarketContextCards from "$lib/components/symbol/SymbolMarketContextCards.svelte";
  import SymbolMonitoringRail from "$lib/components/symbol/SymbolMonitoringRail.svelte";
  import SymbolPastNotesPanel from "$lib/components/symbol/SymbolPastNotesPanel.svelte";
  import SymbolSnapshotCard from "$lib/components/symbol/SymbolSnapshotCard.svelte";
  import SymbolTimeframeBoard from "$lib/components/symbol/SymbolTimeframeBoard.svelte";
  import SymbolTimeframeBar from "$lib/components/symbol/SymbolTimeframeBar.svelte";
  import type { PageProps } from "./$types";

  type PastNoteMutation = {
    token: number;
    symbol: string;
    draftRevision: number;
  };

  type PastNoteFeedback = {
    error: string | null;
    notice: string | null;
  };

  const newerDraftSaveNotice = "送信時点の内容を保存しました。追加の変更は未保存です";

  let { data }: PageProps = $props();

  const rankingTimeframes = ["5m", "15m", "1h", "4h", "24h", "74h"] as const;
  const rankingMetrics = [
    { id: "changeUp", label: "上昇順" },
    { id: "changeDown", label: "下落順" },
    { id: "turnoverTop", label: "売買代金" },
    { id: "volumeUp", label: "出来高倍率" }
  ] as const;

  let pastNotes = $state<PastNote[]>([]);
  let noteReason = $state("");
  let noteText = $state("");
  let noteDraftRevision = 0;
  let noteDraftLastEditedSymbol: string | null = null;
  let activePastNoteMutation = $state<PastNoteMutation | null>(null);
  let pastNoteMutationSequence = 0;
  let pastNoteFeedbackBySymbol = $state<Record<string, PastNoteFeedback>>({});
  let draftSymbol = $state<string | null>(null);

  let serverPastNotes = $derived((data.pastNotes ?? []).filter(isPastNote));
  let row = $derived(data.row);
  let selectedTimeframe = $derived(data.timeframe);
  let range = $derived(range24h(row));
  let displaySymbol = $derived(formatDisplaySymbol(row.symbol));
  let selectedSignals = $derived(movementSignals(row, selectedTimeframe));
  let selectedPastNotes = $derived(filterPastNotesBySymbol(pastNotes, row.symbol));
  let rankingContext = $derived(
    rankingMetrics.map((metric) => ({
      ...metric,
      result: rankingPosition(data.snapshot.rankings, selectedTimeframe, metric.id, row.symbol)
    }))
  );
  let timeframeRows = $derived(
    rankingTimeframes.map((timeframe) => ({
      timeframe,
      change: row.changePctByTf?.[timeframe],
      turnover: row.turnoverUsdtByTf?.[timeframe],
      volumeRatio: row.volumeRatioByTf?.[timeframe]
    }))
  );
  let noteSaveError = $derived(pastNoteFeedbackBySymbol[row.symbol]?.error ?? null);
  let noteSaveNotice = $derived(pastNoteFeedbackBySymbol[row.symbol]?.notice ?? null);
  let isNoteSaving = $derived(activePastNoteMutation !== null);

  $effect(() => {
    pastNotes = serverPastNotes;
  });

  $effect(() => {
    if (draftSymbol === null) {
      draftSymbol = row.symbol;
      return;
    }
    if (draftSymbol === row.symbol) return;
    draftSymbol = row.symbol;
    resetPastNoteDraft();
  });

  function resetPastNoteDraft() {
    noteReason = "";
    noteText = "";
    noteDraftRevision += 1;
    noteDraftLastEditedSymbol = null;
  }

  function setNoteReason(value: string) {
    clearPastNoteFeedbackForEdit();
    noteReason = value;
    noteDraftRevision += 1;
    noteDraftLastEditedSymbol = row.symbol;
  }

  function setNoteText(value: string) {
    clearPastNoteFeedbackForEdit();
    noteText = value;
    noteDraftRevision += 1;
    noteDraftLastEditedSymbol = row.symbol;
  }

  function clearPastNoteFeedbackForEdit() {
    const feedback = pastNoteFeedbackBySymbol[row.symbol];
    if (!feedback || feedback.notice === newerDraftSaveNotice) return;
    setPastNoteFeedback(row.symbol, { error: null, notice: null });
  }

  function setPastNoteFeedback(symbol: string, feedback: PastNoteFeedback) {
    pastNoteFeedbackBySymbol[symbol] = feedback;
  }

  function isCurrentPastNoteMutation(mutation: PastNoteMutation) {
    const currentMutation = activePastNoteMutation;
    return currentMutation?.token === mutation.token && currentMutation.symbol === mutation.symbol;
  }

  function finishPastNoteMutation(mutation: PastNoteMutation) {
    if (isCurrentPastNoteMutation(mutation)) activePastNoteMutation = null;
  }

  async function savePastNote() {
    if (activePastNoteMutation !== null) return;
    const reason = noteReason.trim();
    const note = noteText.trim();
    if (!reason && !note) return;

    const mutation: PastNoteMutation = {
      token: ++pastNoteMutationSequence,
      symbol: row.symbol,
      draftRevision: noteDraftRevision
    };
    activePastNoteMutation = mutation;
    setPastNoteFeedback(mutation.symbol, { error: null, notice: null });
    try {
      const savedNotes = await savePastNoteRecord({ symbol: mutation.symbol, reason, note });
      const savedNotesForSymbol = filterPastNotesBySymbol(savedNotes, mutation.symbol);
      if (!isCurrentPastNoteMutation(mutation)) return;

      const hasNewerSameSymbolDraft =
        row.symbol === mutation.symbol &&
        noteDraftLastEditedSymbol === mutation.symbol &&
        noteDraftRevision !== mutation.draftRevision;
      if (row.symbol === mutation.symbol) {
        pastNotes = savedNotesForSymbol;
        if (noteDraftRevision === mutation.draftRevision) {
          resetPastNoteDraft();
        }
      }
      setPastNoteFeedback(mutation.symbol, {
        error: null,
        notice: hasNewerSameSymbolDraft
          ? newerDraftSaveNotice
          : "銘柄注記を保存しました"
      });
    } catch {
      if (isCurrentPastNoteMutation(mutation)) {
        setPastNoteFeedback(mutation.symbol, {
          error: "銘柄注記の保存に失敗しました",
          notice: null
        });
      }
    } finally {
      finishPastNoteMutation(mutation);
    }
  }

  function focusFragmentTarget(event: MouseEvent) {
    const hash = (event.currentTarget as HTMLAnchorElement).hash;
    if (!hash) return;

    requestAnimationFrame(() => {
      document.getElementById(decodeURIComponent(hash.slice(1)))?.focus({ preventScroll: true });
    });
  }
</script>

<svelte:head>
  <title>{displaySymbol} 監視 | 準備監視板</title>
  <meta
    name="description"
    content={`${displaySymbol} のチャート、時間軸、売買代金、リスク、銘柄注記を確認する市場監視画面。`}
  />
</svelte:head>

<main id="symbol-analysis-top" class="symbol-page" tabindex="-1">
  <SymbolHeader {row} {selectedTimeframe} />

  <nav class="section-jumps" aria-label="個別分析内を移動">
    <a href="#symbol-chart" onclick={focusFragmentTarget}>チャート</a>
    <a href="#symbol-monitoring" onclick={focusFragmentTarget}>監視材料</a>
    <a href="#symbol-timeframes" onclick={focusFragmentTarget}>時間軸</a>
    <a href="#symbol-market-context" onclick={focusFragmentTarget}>市場条件</a>
    <a href="#symbol-past-notes" onclick={focusFragmentTarget}>銘柄注記</a>
  </nav>

  <section class="analysis-shell" aria-label={`${displaySymbol} 分析`}>
    <section id="symbol-chart" class="chart-stage" aria-label="主チャート" tabindex="-1">
      <SymbolTimeframeBar symbol={row.symbol} {selectedTimeframe} timeframes={rankingTimeframes} />
      <MarketChart row={row} timeframe={selectedTimeframe} runId={data.snapshot.runId} size="analysis" />
    </section>

    <SymbolMonitoringRail {row} {selectedTimeframe} {rankingContext} {selectedSignals} />
  </section>

  <SymbolTimeframeBoard symbol={row.symbol} {selectedTimeframe} rows={timeframeRows} />

  <section class="intel-grid" data-symbol-workspace aria-label="補助情報">
    <SymbolMarketContextCards {row} {range} />

    <SymbolPastNotesPanel
      notes={selectedPastNotes}
      {noteReason}
      {noteText}
      {noteSaveError}
      {noteSaveNotice}
      {isNoteSaving}
      onReasonChange={setNoteReason}
      onTextChange={setNoteText}
      onSavePastNote={savePastNote}
    />

    <SymbolSnapshotCard snapshot={data.snapshot} />
  </section>

  <a class="back-to-analysis-top" href="#symbol-analysis-top" onclick={focusFragmentTarget}>分析上部へ戻る</a>
</main>

<style>
  /* Symbol order: chart → monitoring evidence → timeframe → one flat support workspace. */
  .symbol-page {
    min-height: 100vh;
    padding: 12px;
    box-sizing: border-box;
    background: var(--bg-alt);
  }

  .section-jumps,
  .back-to-analysis-top {
    display: none;
  }

  .analysis-shell,
  .intel-grid {
    max-width: 1440px;
    margin: 0 auto;
  }

  .analysis-shell {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 330px;
    gap: 8px;
    align-items: start;
  }

  .chart-stage {
    border: 1px solid var(--line);
    background: var(--panel);
  }

  .intel-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    margin-top: 8px;
    border: 1px solid var(--line);
    background: var(--panel);
    box-shadow: none;
  }

  .intel-grid > :global([data-symbol-workspace-section]) {
    min-width: 0;
    border: 0;
    border-bottom: 1px solid var(--line);
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .intel-grid > :global(.context-section:nth-child(odd)) {
    border-right: 1px solid var(--line);
  }

  .intel-grid > :global([data-symbol-workspace-section]:last-child) {
    border-bottom: 0;
  }

  :global(#symbol-chart),
  :global(#symbol-monitoring),
  :global(#symbol-timeframes),
  :global(#symbol-market-context),
  :global(#symbol-past-notes) {
    scroll-margin-top: 56px;
  }

  @media (max-width: 1080px) {
    .analysis-shell {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 720px) {
    .symbol-page {
      padding: 10px;
    }

    .section-jumps {
      position: sticky;
      z-index: 5;
      top: 0;
      display: flex;
      max-width: 100%;
      min-width: 0;
      margin: var(--space-sm) auto;
      overflow-x: auto;
      overscroll-behavior-x: contain;
      border-block: 1px solid var(--line);
      background: var(--bg-alt);
      scrollbar-width: thin;
    }

    .section-jumps a {
      display: grid;
      flex: 0 0 auto;
      place-items: center;
      min-width: 44px;
      min-height: 44px;
      border-right: 1px solid var(--line);
      padding-inline: var(--space-md);
      color: var(--chip-neutral);
      font-size: var(--type-body-sm-size);
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }

    .section-jumps a:focus-visible {
      outline-offset: -2px;
    }

    .section-jumps a:active {
      background: var(--panel-strong);
      color: var(--text);
    }

    .intel-grid {
      grid-template-columns: 1fr;
    }

    .intel-grid > :global(.context-section:nth-child(odd)) {
      border-right: 0;
    }

    .back-to-analysis-top {
      display: grid;
      place-items: center;
      max-width: 1440px;
      min-height: 44px;
      margin: var(--space-sm) auto 0;
      border: 1px solid var(--line);
      color: var(--chip-neutral);
      font-size: var(--type-body-sm-size);
      font-weight: 700;
      text-decoration: none;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .section-jumps a:hover,
    .back-to-analysis-top:hover {
      border-color: var(--focus);
      color: var(--focus);
    }
  }
</style>
