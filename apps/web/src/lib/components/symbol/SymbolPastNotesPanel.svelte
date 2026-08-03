<script lang="ts">
  import { formatDateTime as fmtDate } from "$lib/market/format";
  import type { PastNote } from "$lib/past-note/past-note";
  import { pastNoteSummary } from "$lib/past-note/past-note-view";
  import { PAST_NOTE_HELP_TEXT } from "$lib/ux/monitoring-guidance";

  let {
    notes,
    noteReason,
    noteText,
    noteSaveError,
    noteSaveNotice,
    isNoteSaving,
    onReasonChange,
    onTextChange,
    onSavePastNote
  }: {
    notes: PastNote[];
    noteReason: string;
    noteText: string;
    noteSaveError: string | null;
    noteSaveNotice: string | null;
    isNoteSaving: boolean;
    onReasonChange: (value: string) => void;
    onTextChange: (value: string) => void;
    onSavePastNote: () => void | Promise<void>;
  } = $props();

  function inputValue(event: Event) {
    return (event.currentTarget as HTMLInputElement | HTMLTextAreaElement).value;
  }
</script>

<section id="symbol-past-notes" class="intel-card span-2" data-symbol-workspace-section tabindex="-1">
  <h2>銘柄注記</h2>
  <p class="help-text">{PAST_NOTE_HELP_TEXT}</p>
  <div class="note-list">
    {#each notes as note}
      <article>
        <strong>{note.reason}</strong>
        <span>{fmtDate(note.observedAt)}</span>
        <p>{pastNoteSummary(note)}</p>
      </article>
    {:else}
      <p class="empty">銘柄注記なし</p>
    {/each}
  </div>
  <div class="note-form">
    <label>
      <span>理由</span>
      <input value={noteReason} placeholder="例: 前回急変" oninput={(event) => onReasonChange(inputValue(event))} />
    </label>
    <label>
      <span>メモ</span>
      <textarea
        value={noteText}
        rows="2"
        placeholder="短い参考メモ"
        oninput={(event) => onTextChange(inputValue(event))}
      ></textarea>
    </label>
    <button
      aria-busy={isNoteSaving}
      aria-describedby="past-note-save-status"
      data-single-line-action
      onclick={onSavePastNote}
      disabled={isNoteSaving || (!noteReason.trim() && !noteText.trim())}
    >
      {isNoteSaving ? "保存中" : "銘柄注記を保存"}
    </button>
    <p id="past-note-save-status" class="save-status">
      {isNoteSaving
        ? "銘柄注記を保存中です"
        : !noteReason.trim() && !noteText.trim()
          ? "理由またはメモを入力すると保存できます"
          : "入力内容を銘柄注記として保存できます"}
    </p>
    {#if noteSaveError}
      <p class="note-error" role="alert">{noteSaveError}</p>
    {/if}
    {#if noteSaveNotice}
      <p class="note-notice" role="status" aria-live="polite">{noteSaveNotice}</p>
    {/if}
  </div>
</section>

<style>
  input,
  textarea {
    box-sizing: border-box;
    width: 100%;
    border: 1px solid color-mix(in srgb, var(--muted) 55%, transparent);
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

  button {
    min-height: 34px;
    border: 1px solid color-mix(in srgb, var(--muted) 55%, transparent);
    background: color-mix(in srgb, var(--panel-strong) 90%, transparent);
    color: inherit;
    font: inherit;
    font-weight: 800;
    cursor: pointer;
    padding: 0 12px;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.5;
  }

  h2,
  p {
    margin: 0;
  }

  .intel-card {
    min-width: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    padding: 12px;
  }

  .intel-card h2 {
    font-size: 15px;
  }

  .help-text {
    margin-top: 8px;
    color: var(--muted);
    font-size: 12px;
    line-height: 1.45;
  }

  .span-2 {
    grid-column: span 2;
  }

  .note-list {
    display: grid;
    gap: 0;
    margin-top: 10px;
  }

  .note-list article {
    border: 0;
    border-top: 1px solid var(--line);
    border-radius: 0;
    padding: 10px 0;
    background: transparent;
    box-shadow: none;
  }

  .note-list strong,
  .note-list span {
    display: block;
  }

  .note-list span {
    margin-top: 3px;
    color: var(--muted);
    font-size: 11px;
  }

  .note-list p {
    margin-top: 8px;
    overflow-wrap: anywhere;
    font-size: 13px;
    line-height: 1.45;
  }

  .note-form {
    display: grid;
    gap: 8px;
    margin-top: 10px;
  }

  .note-form label {
    display: grid;
    gap: 4px;
    min-width: 0;
    color: var(--muted);
    font-size: 12px;
  }

  .note-error {
    margin-top: 8px;
    color: var(--quality-risk);
    font-size: 12px;
    line-height: 1.45;
  }

  .note-notice {
    margin-top: 8px;
    color: var(--warning);
    font-size: 12px;
    line-height: 1.45;
  }

  .save-status {
    color: var(--muted);
    font-size: 11px;
    line-height: 1.35;
  }

  input:focus-visible,
  textarea:focus-visible,
  button:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  button:active:not(:disabled) {
    background: var(--panel-strong);
  }

  .empty {
    margin-top: 10px;
    color: var(--muted);
    font-size: 13px;
  }

  @media (max-width: 720px) {
    .span-2 {
      grid-column: auto;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    input,
    button {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    button:hover:not(:disabled) {
      border-color: var(--focus);
      color: var(--focus);
    }
  }
</style>
