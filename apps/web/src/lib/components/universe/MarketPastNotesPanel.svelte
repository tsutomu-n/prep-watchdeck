<script lang="ts">
  import type { MarketPastNote, MarketPastNoteContext } from "$lib/market-past-note/market-past-note";
  import { pastNoteSnapshotFromPayload } from "$lib/market-past-note/market-past-note";
  import { formatTimestamp } from "$lib/market/universe-view";

  let { venueInstrumentId, venueInstrumentVersionId, metricContext = null }: {
    venueInstrumentId: string; venueInstrumentVersionId: number;
    metricContext?: Pick<MarketPastNoteContext, "metricGenerationId" | "oi15mPct" | "trade15mPct"> | null;
  } = $props();

  let notes = $state<MarketPastNote[]>([]);
  let reason = $state("");
  let note = $state("");
  let attachContext = $state(false);
  let loading = $state(false);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let savedMessage = $state<string | null>(null);
  let storageWarning = $state<string | null>(null);
  let revisionToken = $state<string | null>(null);
  let draftRevision = $state(0);
  let activeKey = "";
  const drafts = new Map<string, { reason: string; note: string; revision: number }>();
  const pending = new Set<string>();

  function draftKey(id: string, version: number) {
    return `${id}/${version}`;
  }

  function rememberDraft() {
    if (!activeKey) return;
    const draft = { reason, note, revision: draftRevision };
    drafts.set(activeKey, draft);
    try { window.sessionStorage.setItem(`market-note-draft:${activeKey}`, JSON.stringify(draft)); }
    catch { storageWarning = "未保存メモはこの画面を閉じると失われます"; }
  }

  function restoredDraft(key: string) {
    const memory = drafts.get(key);
    if (memory) return memory;
    try {
      const stored = window.sessionStorage.getItem(`market-note-draft:${key}`);
      if (!stored) return null;
      const value: unknown = JSON.parse(stored);
      if (!value || typeof value !== "object") return null;
      const draft = value as { reason?: unknown; note?: unknown; revision?: unknown };
      if (typeof draft.reason !== "string" || draft.reason.length > 200 ||
          typeof draft.note !== "string" || draft.note.length > 10_000 ||
          !Number.isSafeInteger(draft.revision)) return null;
      return { reason: draft.reason, note: draft.note, revision: Number(draft.revision) };
    } catch {
      storageWarning = "保存済み下書きを読めません。入力中の内容はこの画面で保持します";
      return null;
    }
  }

  function updateReason(value: string) {
    reason = value;
    draftRevision += 1;
    rememberDraft();
  }

  function updateNote(value: string) {
    note = value;
    draftRevision += 1;
    rememberDraft();
  }

  $effect(() => {
    const instrumentId = venueInstrumentId;
    const versionId = venueInstrumentVersionId;
    const key = draftKey(instrumentId, versionId);
    if (activeKey !== key) {
      rememberDraft();
      activeKey = key;
      const draft = restoredDraft(key);
      reason = draft?.reason ?? "";
      note = draft?.note ?? "";
      draftRevision = draft?.revision ?? 0;
      savedMessage = null;
      notes = [];
      revisionToken = null;
      saving = pending.has(key);
    }
    const controller = new AbortController();
    loading = true;
    errorMessage = null;
    fetch(`/api/market-past-notes?venueInstrumentId=${encodeURIComponent(instrumentId)}`, {
      signal: controller.signal
    })
      .then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        const parsed = pastNoteSnapshotFromPayload(await response.json());
        if (!parsed) throw new Error("invalid past notes response");
        if (!controller.signal.aborted && activeKey === key) {
          notes = parsed.notes;
          revisionToken = parsed.revisionToken;
        }
      })
      .catch((cause) => {
        if (!controller.signal.aborted && activeKey === key) {
          errorMessage = cause instanceof Error ? cause.message : "銘柄注記を取得できません";
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && activeKey === key) loading = false;
      });
    return () => controller.abort();
  });

  async function save() {
    const instrumentId = venueInstrumentId;
    const versionId = venueInstrumentVersionId;
    const key = draftKey(instrumentId, versionId);
    const capturedReason = reason.trim();
    const capturedNote = note.trim();
    const capturedRevision = draftRevision;
    const token = revisionToken;
    const context: MarketPastNoteContext | undefined = attachContext ? {
      kind: "ui-observation-v1",
      venueInstrumentId: instrumentId,
      venueInstrumentVersionId: versionId,
      view: "native",
      capturedAt: new Date().toISOString(),
      metricGenerationId: metricContext?.metricGenerationId ?? null,
      oi15mPct: metricContext?.oi15mPct ?? null,
      trade15mPct: metricContext?.trade15mPct ?? null
    } : undefined;
    if ((!capturedReason && !capturedNote) || token === null || pending.has(key)) return;
    pending.add(key);
    saving = true;
    errorMessage = null;
    savedMessage = null;
    try {
      const response = await fetch("/api/market-past-notes", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          venueInstrumentId: instrumentId,
          venueInstrumentVersionId: versionId,
          reason: capturedReason,
          note: capturedNote,
          expectedRevisionToken: token,
          ...(context ? { context } : {})
        })
      });
      if (!response.ok) throw new Error(await response.text());
      const parsed = pastNoteSnapshotFromPayload(await response.json());
      if (!parsed) throw new Error("invalid past notes response");
      if (activeKey === key) {
        notes = parsed.notes;
        revisionToken = parsed.revisionToken;
        if (draftRevision === capturedRevision) {
          reason = "";
          note = "";
          draftRevision += 1;
          rememberDraft();
          try { window.sessionStorage.removeItem(`market-note-draft:${key}`); }
          catch { /* The cleared in-memory draft remains authoritative. */ }
        }
        savedMessage = `${instrumentId} に保存しました`;
      }
    } catch (cause) {
      if (activeKey === key) {
        errorMessage = cause instanceof Error ? cause.message : "銘柄注記を保存できません。再読込して確認してください。";
      }
    } finally {
      pending.delete(key);
      if (activeKey === key) saving = false;
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
          {#if item.context}<small>保存時の指標: 数量OI 15m {item.context.oi15mPct === null ? "—" : `${item.context.oi15mPct}%`} · 確定終値 15m {item.context.trade15mPct === null ? "—" : `${item.context.trade15mPct}%`}</small>{/if}
        </li>
      {/each}
    </ul>
  {/if}

  <div class="note-form">
    <label>
      <span>理由</span>
      <input value={reason} oninput={(event) => updateReason(event.currentTarget.value)} placeholder="例: 流動性を再確認" />
    </label>
    <label>
      <span>短い観測メモ</span>
      <textarea value={note} oninput={(event) => updateNote(event.currentTarget.value)} rows="2" placeholder="売買記録ではなく、後で確認する事実"></textarea>
    </label>
    <label class="context-choice"><input type="checkbox" bind:checked={attachContext} />保存時の指標を添付する</label>
    <button
      type="button"
      onclick={save}
      disabled={saving || revisionToken === null || (!reason.trim() && !note.trim())}
      aria-busy={saving}
      aria-describedby="market-past-note-status"
    >{saving ? "保存中" : "注記を保存"}</button>
    <p id="market-past-note-status" class="form-status">
      {!reason.trim() && !note.trim()
        ? "理由またはメモを入力すると保存できます"
        : "選択中のvenueInstrumentIdへ保存します"}
    </p>
    {#if errorMessage}<p class="error" role="alert">{errorMessage}</p>{/if}
    {#if storageWarning}<p class="error" role="status">{storageWarning}</p>{/if}
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

  .context-choice {
    display: flex;
    align-items: center;
  }

  .context-choice input {
    width: auto;
    min-height: auto;
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
