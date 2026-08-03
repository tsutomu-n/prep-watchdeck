<script lang="ts">
  import MarketChart from "$lib/MarketChart.svelte";
  import SelectedSymbolDetailGroup from "$lib/components/dashboard/SelectedSymbolDetailGroup.svelte";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { formatNumber as fmt } from "$lib/market/format";
  import { codeLabel } from "$lib/market/labels";
  import type { Range24h } from "$lib/market/row-analysis";
  import type { PastNote } from "$lib/past-note/past-note";
  import { pastNoteSummary } from "$lib/past-note/past-note-view";
  import { PAST_NOTE_HELP_TEXT } from "$lib/ux/monitoring-guidance";

  let {
    row,
    snapshotRunId,
    selectedTimeframe,
    range,
    selectedPastNotes,
    noteReason,
    noteText,
    noteSaveError,
    isSaving = false,
    saveNotice = null,
    onNoteReasonChange,
    onNoteTextChange,
    onSavePastNote
  }: {
    row: ScannerRowDTO;
    snapshotRunId: string;
    selectedTimeframe: string;
    range: Range24h | null;
    selectedPastNotes: PastNote[];
    noteReason: string;
    noteText: string;
    noteSaveError: string | null;
    isSaving?: boolean;
    saveNotice?: string | null;
    onNoteReasonChange: (value: string) => void;
    onNoteTextChange: (value: string) => void;
    onSavePastNote: () => void | Promise<void>;
  } = $props();

  let isNoteSaveDisabled = $derived(isSaving || (!noteReason.trim() && !noteText.trim()));
  let hasOpenedChart = $state(false);

  function trackContextOpen(open: boolean) {
    if (open) hasOpenedChart = true;
  }
</script>

<SelectedSymbolDetailGroup
  group="context"
  title="チャート / 銘柄注記 / 理由"
  description="レンジ / 銘柄注記 / risk code"
  badge={selectedPastNotes.length > 0 ? `${selectedPastNotes.length}件` : "なし"}
  onToggle={trackContextOpen}
>
  {#if range}
    <section class="range-panel" aria-label="24時間レンジ位置">
      <div class="range-head">
        <h3>24hレンジ</h3>
        <span>{range.bars === 0 ? "現在値情報から算出" : range.bars >= 288 ? "5分足から算出" : "日足から概算"}</span>
      </div>
      <div class="range-track">
        <span class="range-marker" style={`left: ${range.positionPct}%`}></span>
      </div>
      <div class="range-values">
        <span>安値 {fmt(range.low)}</span>
        <strong>現在 {fmt(range.close)}</strong>
        <span>高値 {fmt(range.high)}</span>
      </div>
    </section>
  {/if}
  {#if hasOpenedChart}
    <MarketChart {row} timeframe={selectedTimeframe} runId={snapshotRunId} />
  {/if}
  <section class="past-note">
    <h3>銘柄注記</h3>
    <p class="help-text">{PAST_NOTE_HELP_TEXT}</p>
    {#if selectedPastNotes.length > 0}
      {#each selectedPastNotes as note}
        <p>{pastNoteSummary(note)}</p>
      {/each}
    {:else}
      <p class="empty">銘柄注記なし</p>
    {/if}
    <div class="note-form">
      <label>
        <span>理由</span>
        <input value={noteReason} placeholder="例: 前回急変" oninput={(event) => onNoteReasonChange(event.currentTarget.value)} />
      </label>
      <label>
        <span>メモ</span>
        <textarea
          value={noteText}
          rows="2"
          placeholder="短い参考メモ"
          oninput={(event) => onNoteTextChange(event.currentTarget.value)}
        ></textarea>
      </label>
      <button
        type="button"
        aria-busy={isSaving}
        aria-describedby="dashboard-past-note-save-status"
        data-single-line-action
        onclick={onSavePastNote}
        disabled={isNoteSaveDisabled}
      >{isSaving ? "保存中" : "銘柄注記を保存"}</button>
      <p id="dashboard-past-note-save-status" class="save-status">
        {isSaving
          ? "銘柄注記を保存しています"
          : isNoteSaveDisabled
            ? "理由またはメモを入力すると保存できます"
            : "入力内容を銘柄注記として保存できます"}
      </p>
      {#if saveNotice}
        <p class="save-notice" role="status" aria-live="polite">{saveNotice}</p>
      {/if}
      {#if noteSaveError}
        <p class="note-error" role="alert">{noteSaveError}</p>
      {/if}
    </div>
  </section>
  <section class="codes">
    <h3>理由</h3>
    <div>
      {#each row.reasonCodes ?? [] as code}<span>{codeLabel(code)}</span>{/each}
    </div>
    <h3>リスク</h3>
    <div>
      {#each row.riskTagCodes ?? [] as code}<span class="risk-chip">{codeLabel(code)}</span>{:else}<span>なし</span>{/each}
    </div>
  </section>
</SelectedSymbolDetailGroup>

<style>
  h3,
  p {
    margin: 0;
  }

  .range-panel {
    padding: 12px;
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel);
  }

  .range-panel h3,
  .past-note h3,
  .codes h3 {
    font-size: 12px;
    color: var(--subtle);
  }

  .range-head,
  .range-values {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .range-head span,
  .range-values span {
    color: var(--subtle);
    font-size: 11px;
  }

  .range-values strong {
    color: var(--text);
    font-size: 11px;
    font-weight: 700;
  }

  .range-track {
    position: relative;
    height: 8px;
    margin: 12px 0 8px;
    border: 1px solid var(--chip-line);
    background: linear-gradient(
      90deg,
      var(--down) 0%,
      var(--warning) 50%,
      var(--up) 100%
    );
  }

  .range-marker {
    position: absolute;
    top: -5px;
    width: 2px;
    height: 18px;
    background: var(--text);
    box-shadow: 0 0 0 1px var(--bg-alt);
    transform: translateX(-1px);
  }

  .past-note {
    padding: 12px;
    border-bottom: 1px solid var(--line-strong);
  }

  .past-note p {
    margin-top: 8px;
    overflow-wrap: anywhere;
    font-size: 13px;
  }

  .past-note .help-text {
    color: var(--subtle);
    font-size: 12px;
    line-height: 1.45;
  }

  .empty {
    color: var(--subtle);
  }

  .note-form {
    display: grid;
    gap: 8px;
    margin-top: 12px;
  }

  .note-form label {
    display: grid;
    gap: 5px;
    color: var(--subtle);
    font-size: 12px;
  }

  input,
  textarea {
    box-sizing: border-box;
    width: 100%;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: var(--panel-strong);
    color: var(--text);
    font: inherit;
  }

  input {
    min-height: 34px;
    padding: 0 10px;
  }

  textarea {
    min-height: 58px;
    padding: 8px 10px;
    resize: vertical;
  }

  input:focus-visible,
  textarea:focus-visible,
  .note-form button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 1px;
    border-color: var(--focus);
  }

  .note-form button {
    min-height: 38px;
    border: 1px solid var(--focus);
    background: var(--focus);
    color: var(--focus-on);
    cursor: pointer;
    font: inherit;
    white-space: nowrap;
  }

  .note-form button:disabled {
    cursor: not-allowed;
    opacity: 0.45;
  }

  .note-error {
    color: var(--quality-risk);
    font-size: 12px;
  }

  .save-notice {
    color: var(--quality-good);
    font-size: 12px;
  }

  .save-status {
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    input,
    .note-form button {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  .codes {
    padding: 12px;
  }

  .codes h3 {
    margin-top: 12px;
  }

  .codes div {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }

  .codes span {
    border: 1px solid var(--chip-line);
    padding: 5px 7px;
    font-size: 11px;
  }

  .codes .risk-chip {
    border-color: var(--warning-border);
    color: var(--warning);
  }
</style>
