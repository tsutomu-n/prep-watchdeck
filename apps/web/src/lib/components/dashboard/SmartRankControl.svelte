<script lang="ts">
  import { formatNumber as fmt } from "$lib/market/format";
  import { codeLabel, dataQualityLabel } from "$lib/market/labels";
  import type { SmartRankState } from "$lib/market/smart-rank";

  let {
    state,
    targetLimit,
    maxTargetLimit,
    availableRows,
    canRun,
    cooldownSeconds,
    onTargetLimitChange,
    onRun
  }: {
    state: SmartRankState | null;
    targetLimit: string;
    maxTargetLimit: number;
    availableRows: number;
    canRun: boolean;
    cooldownSeconds: number;
    onTargetLimitChange: (value: string) => void;
    onRun: () => void;
  } = $props();

  function inputValue(event: Event) {
    return (event.currentTarget as HTMLInputElement).value;
  }

  let runStatus = $derived(
    cooldownSeconds > 0
      ? `再実行まで${cooldownSeconds}秒です`
      : availableRows <= 0
        ? "現在の表示条件に対象銘柄がないため実行できません"
        : "現在のRaw Sort上位を監視優先度で並べ直します"
  );
</script>

<section class="smart-rank" aria-label="Smart Rank">
  <div class="smart-rank-head">
    <div>
      <h2>Smart Rank</h2>
    </div>
    <label>
      <span>対象上限</span>
      <input
        aria-label="Smart Rank対象上限"
        inputmode="numeric"
        min="1"
        max={maxTargetLimit}
        type="number"
        value={targetLimit}
        oninput={(event) => onTargetLimitChange(inputValue(event))}
      />
    </label>
    <button
      type="button"
      aria-describedby="smart-rank-run-status"
      data-single-line-action
      onclick={onRun}
      disabled={!canRun}
    >
      {cooldownSeconds > 0 ? `${cooldownSeconds}s` : "この上位をSmart Rank"}
    </button>
  </div>

  <p id="smart-rank-run-status" class="run-status">{runStatus}</p>

  <p class="smart-rank-note">
    Smart Rankは、現在のRaw Sort上位候補を監視優先度とデータ品質で並べ直す補助表示です。
  </p>

  {#if state}
    <div class="smart-rank-meta">
      <span>{state.base.timeframe} / {state.base.sortKey} / {state.base.sortDirection}</span>
      <span>対象 {state.base.targetSymbols.length} / 表示 {availableRows}</span>
      <span>{new Date(state.base.createdAt).toLocaleTimeString("ja-JP")}</span>
    </div>
    <ol class="smart-rank-list">
      {#each state.rows.slice(0, 8) as item}
        <li>
          <a href={`/symbols/${encodeURIComponent(item.row.symbol)}?tf=${state.base.timeframe}`}>
            <span>
              <strong>{item.row.symbol}</strong>
              <em>raw #{item.sourceRank} / {codeLabel(item.row.label)}</em>
            </span>
            <span class="priority">
              <small>監視優先度</small>
              <b>{fmt(item.smartScore)}</b>
            </span>
            <span>{item.warningCount}警戒</span>
            <span>{dataQualityLabel(item.row.dataQuality)}</span>
          </a>
        </li>
      {/each}
    </ol>
  {:else}
    <p class="empty">未実行。Raw Sortで絞った後、必要な時だけ押してください。</p>
  {/if}
</section>

<style>
  .smart-rank {
    border: 0;
    border-block: 1px solid var(--line);
    background: transparent;
    padding: 10px;
  }

  .smart-rank-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 92px auto;
    align-items: end;
    gap: 8px;
  }

  .smart-rank-note,
  .empty,
  .smart-rank-meta,
  .smart-rank-list em {
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: 16px;
  }

  label {
    display: grid;
    gap: 3px;
    color: var(--subtle);
    font-size: 10px;
  }

  input {
    box-sizing: border-box;
    min-height: 32px;
    width: 100%;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: var(--panel-strong);
    color: var(--text);
    font: inherit;
    padding: 0 8px;
  }

  input:focus-visible,
  button:focus-visible,
  .smart-rank-list a:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
    border-color: var(--focus);
  }

  button {
    min-height: 32px;
    border: 1px solid color-mix(in srgb, var(--focus) 45%, transparent);
    background: color-mix(in srgb, var(--focus) 10%, transparent);
    color: var(--focus);
    cursor: pointer;
    font: inherit;
    font-size: 12px;
    font-weight: 800;
    padding: 0 10px;
    white-space: nowrap;
  }

  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .smart-rank-note {
    margin-top: 8px;
  }

  .run-status {
    margin-top: 8px;
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  .smart-rank-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
  }

  .smart-rank-list {
    display: grid;
    gap: 0;
    margin: 8px 0 0;
    padding: 0;
    list-style: none;
  }

  .smart-rank-list a {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 76px 54px 60px;
    gap: 8px;
    align-items: center;
    min-height: 28px;
    border-top: 1px solid color-mix(in srgb, var(--muted) 16%, transparent);
    color: inherit;
    text-decoration: none;
  }

  button:active:not(:disabled),
  .smart-rank-list a:active {
    background: var(--panel-strong);
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    input,
    button,
    .smart-rank-list a {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    button:hover:not(:disabled),
    .smart-rank-list a:hover {
      border-color: var(--focus);
      color: var(--focus);
    }
  }

  .smart-rank-list strong,
  .smart-rank-list em {
    display: block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .priority {
    color: var(--subtle);
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  .priority small,
  .priority b {
    display: block;
  }

  .priority small {
    font-size: 9px;
    font-weight: 600;
    line-height: 1.1;
  }

  .priority b {
    color: var(--text);
    font-size: 11px;
    font-weight: 700;
    line-height: 1.15;
  }

  @media (max-width: 560px) {
    .smart-rank-head,
    .smart-rank-list a {
      grid-template-columns: 1fr;
    }
  }
</style>
