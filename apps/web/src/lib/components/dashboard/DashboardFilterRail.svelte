<script lang="ts">
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { categoryLabel } from "$lib/market/labels";

  let {
    rows,
    categoryFilters,
    activeCategory,
    dataAsOf,
    generatedAt,
    isRefreshing,
    refreshError,
    refreshNotice,
    onCategorySelect,
    onReload,
    onRefreshLive
  }: {
    rows: ScannerRowDTO[];
    categoryFilters: readonly string[];
    activeCategory: string;
    dataAsOf: number;
    generatedAt: number;
    isRefreshing: boolean;
    refreshError: string | null;
    refreshNotice: string | null;
    onCategorySelect: (category: string) => void;
    onReload: () => void | Promise<void>;
    onRefreshLive: () => void | Promise<void>;
  } = $props();

  function count(category: string) {
    if (category === "ALL") return rows.length;
    return rows.filter((row) => row.category === category).length;
  }
</script>

<aside class="rail" aria-label="分類">
  {#each categoryFilters as category}
    <button
      type="button"
      class:active={activeCategory === category}
      aria-pressed={activeCategory === category}
      data-single-line-action
      onclick={() => onCategorySelect(category)}
    >
      <span>{categoryLabel(category)}</span>
      <strong>{count(category)}</strong>
    </button>
  {/each}
  <div class="freshness">
    <span>データ時点</span>
    <strong>{new Date(dataAsOf).toLocaleString("ja-JP")}</strong>
    <span>更新時刻</span>
    <strong>{new Date(generatedAt).toLocaleString("ja-JP")}</strong>
    <div class="refresh-actions">
      <button type="button" class="reload-button" data-single-line-action onclick={onReload}>
        再読込
      </button>
      <button
        type="button"
        class="reload-button primary"
        aria-label="service snapshotを更新"
        aria-busy={isRefreshing}
        aria-describedby={isRefreshing ? "refresh-button-status" : undefined}
        data-single-line-action
        onclick={onRefreshLive}
        disabled={isRefreshing}
      >
        <span class="desktop-refresh-label">{isRefreshing ? "更新中" : "service snapshot更新"}</span>
        <span class="mobile-refresh-label">{isRefreshing ? "更新中" : "Snapshot更新"}</span>
      </button>
    </div>
    <span id="refresh-button-status" class="sr-only">
      {isRefreshing ? "service snapshotを更新中です" : "service snapshotを更新できます"}
    </span>
    {#if refreshError}
      <p class="refresh-error" role="alert">{refreshError}</p>
    {/if}
    {#if refreshNotice}
      <p class="refresh-notice" role="status" aria-live="polite">{refreshNotice}</p>
    {/if}
  </div>
</aside>

<style>
  p {
    margin: 0;
  }

  button {
    color: inherit;
    font: inherit;
  }

  .rail {
    border: 1px solid var(--line);
    display: grid;
    align-items: start;
    grid-template-columns: repeat(5, minmax(96px, 1fr)) minmax(300px, 0.9fr);
    gap: 0;
    padding: 0;
    background: var(--panel);
    box-shadow: none;
  }

  .rail button {
    align-self: start;
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    min-height: 34px;
    border: 0;
    border-right: 1px solid color-mix(in srgb, var(--muted) 18%, transparent);
    border-top: 0;
    background: transparent;
    padding: 0 10px;
    color: var(--chip-neutral);
    cursor: pointer;
    white-space: nowrap;
  }

  .rail button.active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
    font-weight: 800;
  }

  .freshness {
    display: grid;
    align-self: start;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 3px 8px;
    min-width: 0;
    padding: 6px 10px;
    color: var(--subtle);
    font-size: 11px;
  }

  .freshness strong {
    display: block;
    color: var(--text);
  }

  .refresh-actions {
    display: grid;
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 4px;
  }

  .reload-button {
    width: 100%;
    min-height: 38px;
    border: 1px solid var(--chip-line);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }

  .mobile-refresh-label {
    display: none;
  }

  .rail button:focus-visible {
    outline: var(--focus-ring-width) solid var(--focus);
    outline-offset: -2px;
  }

  .rail button:active:not(:disabled) {
    background: var(--panel-strong);
  }

  .rail button.active:active:not(:disabled) {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .reload-button:disabled {
    cursor: wait;
    opacity: 0.65;
  }

  .reload-button.primary {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .reload-button.primary:active:not(:disabled) {
    background: color-mix(in srgb, var(--focus) 86%, var(--focus-on));
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    clip-path: inset(50%);
  }

  .refresh-error {
    margin-top: 8px;
    overflow-wrap: anywhere;
    color: var(--quality-risk);
    font-size: 12px;
  }

  .refresh-notice {
    margin-top: 8px;
    overflow-wrap: anywhere;
    color: var(--warning);
    font-size: 12px;
  }

  @media (max-width: 960px) {
    .rail {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .freshness {
      grid-column: 1 / -1;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .rail button,
    .reload-button {
      min-width: var(--control-height-touch);
      min-height: var(--control-height-touch);
    }

    .desktop-refresh-label {
      display: none;
    }

    .mobile-refresh-label {
      display: inline;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .reload-button:hover {
      border-color: var(--focus);
      color: var(--focus);
    }
  }
</style>
