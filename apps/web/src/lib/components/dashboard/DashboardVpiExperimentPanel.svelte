<script lang="ts">
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import {
    buildVpiDiscoveryLane,
    vpiStateLabel,
    type VpiLitePlusItem,
    type VpiLitePlusSummary
  } from "$lib/market/vpi-lite-plus";

  let {
    summary,
    watchlistCount,
    selectableSymbols,
    onSymbolSelect
  }: {
    summary: VpiLitePlusSummary;
    watchlistCount: number;
    selectableSymbols: readonly string[];
    onSymbolSelect: (symbol: string) => void;
  } = $props();

  let lane = $derived(
    buildVpiDiscoveryLane(summary, watchlistCount, new Set(selectableSymbols))
  );

  function itemLabel(item: VpiLitePlusItem) {
    return `${item.symbol}、${vpiStateLabel(item.state)}を選択`;
  }
</script>

<section class="vpi-lane" aria-label="市場活動（VPI-Lite+）">
  <header>
    <div>
      <h3>市場活動</h3>
      <small class="technical-name">VPI-Lite+</small>
      <p>既存の限定対象だけを使う活動発見です。売買シグナルではありません。</p>
    </div>
    <span>{lane.coverageLabel}</span>
  </header>

  {#if lane.status === "no-targets"}
    <p class="lane-status">VPI判定対象なし</p>
  {:else if lane.status === "no-visible-targets"}
    <p class="lane-status">現在の表示条件に該当するVPI対象なし</p>
  {:else if lane.status === "unavailable"}
    <p class="lane-status risk">VPIデータ不足</p>
  {:else if lane.status === "no-match"}
    <p class="lane-status">活動急増なし</p>
  {:else}
    <div class="lane-columns">
      <section aria-label="活動増加">
        <h4>活動増加</h4>
        <ul>
          {#each lane.activity as item (item.symbol)}
            <li>
              <button type="button" aria-label={itemLabel(item)} onclick={() => onSymbolSelect(item.symbol)}>
                <strong title={item.symbol}>{formatDisplaySymbol(item.symbol)}</strong>
                <span>{vpiStateLabel(item.state)}</span>
              </button>
            </li>
          {:else}
            <li class="empty">該当なし</li>
          {/each}
        </ul>
      </section>
      <section aria-label="要注意">
        <h4>要注意</h4>
        <ul>
          {#each lane.caution as item (item.symbol)}
            <li>
              <button type="button" aria-label={itemLabel(item)} onclick={() => onSymbolSelect(item.symbol)}>
                <strong title={item.symbol}>{formatDisplaySymbol(item.symbol)}</strong>
                <span>{vpiStateLabel(item.state)}</span>
              </button>
            </li>
          {:else}
            <li class="empty">該当なし</li>
          {/each}
        </ul>
      </section>
    </div>
  {/if}
</section>

<style>
  .vpi-lane {
    border: 1px solid var(--line-strong);
    border-top: 0;
    background: var(--panel);
  }

  header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-md);
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  h3,
  h4,
  p,
  ul {
    margin: 0;
  }

  h3 {
    font-size: var(--type-heading-md-size);
  }

  h4 {
    padding: var(--space-xs) var(--space-md);
    color: var(--subtle);
    font-size: 11px;
  }

  .technical-name {
    display: block;
    margin-top: 2px;
    color: var(--muted);
    font-size: 9px;
  }

  header p,
  header > span,
  .lane-status,
  .empty {
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  header p {
    margin-top: var(--space-xs);
  }

  header > span {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .lane-status {
    padding: var(--space-md);
  }

  .lane-status.risk {
    color: var(--quality-risk);
  }

  .lane-columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .lane-columns > section + section {
    border-left: 1px solid var(--line);
  }

  ul {
    padding: 0;
    list-style: none;
  }

  li {
    border-top: 1px solid var(--line);
  }

  li.empty {
    padding: var(--space-sm) var(--space-md);
  }

  button {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-sm);
    width: 100%;
    min-height: var(--control-height-touch);
    border: 0;
    background: transparent;
    padding: var(--space-xs) var(--space-md);
    color: var(--text);
    cursor: pointer;
    font: inherit;
    text-align: left;
  }

  button strong {
    overflow-wrap: anywhere;
    font-size: 12px;
  }

  button span {
    color: var(--chip-neutral);
    font-size: 10px;
    text-align: right;
  }

  button:active {
    background: var(--panel-strong);
  }

  @media (hover: hover) and (pointer: fine) {
    button:hover {
      background: var(--surface);
    }
  }

  @media (max-width: 560px) {
    header {
      display: grid;
    }

    .lane-columns {
      grid-template-columns: 1fr;
    }

    .lane-columns > section + section {
      border-top: 1px solid var(--line);
      border-left: 0;
    }

    button {
      min-height: var(--control-height-touch);
    }
  }
</style>
