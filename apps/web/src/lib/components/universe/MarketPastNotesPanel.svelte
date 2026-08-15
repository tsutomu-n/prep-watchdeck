<script lang="ts">
  import type { MarketPastNote } from "$lib/market-past-note/market-past-note";
  import { marketPastNotesFromPayload } from "$lib/market-past-note/market-past-note";
  import { formatTimestamp } from "$lib/market/universe-view";

  let { venueInstrumentId }: { venueInstrumentId: string } = $props();

  let notes = $state<MarketPastNote[]>([]);
  let reason = $state("");
  let note = $state("");
  let loading = $state(false);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let savedMessage = $state<string | null>(null);
  let lastInstrumentId = "";

  $effect(() => {
    const instrumentId = venueInstrumentId;
    if (lastInstrumentId !== instrumentId) {
      lastInstrumentId = instrumentId;
      reason = "";
      note = "";
      savedMessage = null;
    }
    const controller = new AbortController();
    loading = true;
    errorMessage = null;
    fetch(`/api/market-past-notes?venueInstrumentId=${encodeURIComponent(instrumentId)}`, {
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        const parsed = marketPastNotesFromPayload(await response.json());
        if (!parsed) throw new Error("invalid past notes response");
        if (!controller.signal.aborted && venueInstrumentId === instrumentId) notes = parsed;
      })
      .catch((cause) => {
        if (!controller.signal.aborted && venueInstrumentId === instrumentId) {
          errorMessage = cause instanceof Error ? cause.message : "銘柄注記を取得できません";
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && venueInstrumentId === instrumentId) loading = false;
      });
    return () => controller.abort();
  });

  async function save() {
    const instrumentId = venueInstrumentId;
    const capturedReason = reason.trim();
    const capturedNote = note.trim();
    if (!capturedReason && !capturedNote) return;
    saving = true;
    errorMessage = null;
    savedMessage = null;
    try {
      const response = await fetch("/api/market-past-notes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          venueInstrumentId: instrumentId,
          reason: capturedReason,
          note: capturedNote
        })
      });
      if (!response.ok) throw new Error(await response.text());
      const parsed = marketPastNotesFromPayload(await response.json());
      if (!parsed) throw new Error("invalid past notes response");
      if (venueInstrumentId === instrumentId) {
        notes = parsed;
        reason = "";
        note = "";
        savedMessage = `${instrumentId} に保存しました`;
      }
    } catch (cause) {
      if (venueInstrumentId === instrumentId) {
        errorMessage = cause instanceof Error ? cause.message : "銘柄注記を保存できません";
      }
    } finally {
      if (venueInstrumentId === instrumentId) saving = false;
    }
  }
</script>

<section class="notes" aria-labelledby="past-note-title">
  <div class="section-heading">
    <div>
      <h3 id="past-note-title">Past Note</h3>
      <p>60日間の観測メモ。取引記録ではありません。</p>
    </div>
    <code>{venueInstrumentId}</code>
  </div>

  {#if loading}
    <p class="empty" role="status">注記を読み込み中</p>
  {:else if notes.length === 0}
    <p class="empty">このinstrumentの注記はありません</p>
  {:else}
    <ul class="note-list">
      {#each notes as item (item.observedAt)}
        <li>
          <strong>{item.reason}</strong>
          <time datetime={item.observedAt}>{formatTimestamp(item.observedAt)}</time>
          {#if item.note}<p>{item.note}</p>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  <div class="note-form">
    <label>
      <span>理由</span>
      <input bind:value={reason} placeholder="例: 流動性を再確認" />
    </label>
    <label>
      <span>短い観測メモ</span>
      <textarea bind:value={note} rows="2" placeholder="売買記録ではなく、後で確認する事実"></textarea>
    </label>
    <button
      type="button"
      onclick={save}
      disabled={saving || (!reason.trim() && !note.trim())}
      aria-busy={saving}
      aria-describedby="market-past-note-status"
    >{saving ? "保存中" : "注記を保存"}</button>
    <p id="market-past-note-status" class="form-status">
      {!reason.trim() && !note.trim()
        ? "理由またはメモを入力すると保存できます"
        : "選択中のvenueInstrumentIdへ保存します"}
    </p>
    {#if errorMessage}<p class="error" role="alert">{errorMessage}</p>{/if}
    {#if savedMessage}<p class="saved" role="status" aria-live="polite">{savedMessage}</p>{/if}
  </div>
</section>

<style>
  .notes {
    border-top: 1px solid var(--line);
    padding: var(--space-md);
  }

  .section-heading {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: var(--space-sm);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: var(--type-heading-md-size);
  }

  .section-heading p,
  .form-status,
  time,
  .empty {
    color: var(--muted);
    font-size: var(--type-body-sm-size);
  }

  code {
    overflow-wrap: anywhere;
    color: var(--subtle);
    font: inherit;
    font-size: var(--type-label-caps-size);
    text-align: right;
  }

  .note-list {
    display: grid;
    gap: 0;
    margin: var(--space-sm) 0 0;
    padding: 0;
    list-style: none;
  }

  .note-list li {
    display: grid;
    gap: var(--space-xs);
    padding: var(--space-sm) 0;
    border-top: 1px solid var(--line);
  }

  .note-list p {
    overflow-wrap: anywhere;
    font-size: var(--type-body-sm-size);
  }

  .note-form {
    display: grid;
    gap: var(--space-sm);
    margin-top: var(--space-md);
  }

  label {
    display: grid;
    gap: var(--space-xs);
    color: var(--muted);
    font-size: var(--type-body-sm-size);
  }

  input,
  textarea,
  button {
    box-sizing: border-box;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-none);
    background: var(--panel-strong);
    color: var(--text);
    font: inherit;
  }

  input,
  button {
    min-height: var(--control-height-dense);
  }

  input,
  textarea {
    width: 100%;
    padding: var(--space-sm);
  }

  textarea {
    resize: vertical;
  }

  button {
    justify-self: start;
    padding: 0 var(--space-md);
    cursor: pointer;
    font-weight: 800;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .empty {
    padding: var(--space-md) 0;
  }

  .error {
    color: var(--quality-risk);
  }

  .saved {
    color: var(--quality-good);
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    input,
    button {
      min-height: var(--control-height-touch);
    }
  }
</style>
