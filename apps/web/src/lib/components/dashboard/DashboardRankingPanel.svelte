<script lang="ts">
  import { formatNumber as fmt } from "$lib/market/format";
  import type { RankingValue } from "$lib/market/rankings";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";

  let {
    label,
    metric,
    timeframe,
    items,
    totalEligible,
    headingId,
    panelId,
    labelledBy,
    hidden = false,
    volumeRatioHelp = ""
  }: {
    label: string;
    metric: string;
    timeframe: string;
    items: RankingValue[];
    totalEligible: number;
    headingId?: string;
    panelId?: string;
    labelledBy?: string;
    hidden?: boolean;
    volumeRatioHelp?: string;
  } = $props();

  function metricClass() {
    if (metric === "changeUp") return "up";
    if (metric === "changeDown") return "down";
    if (metric === "turnoverTop" || metric === "volumeUp") return "volume";
    return "neutral";
  }

  function valueClass(value: number) {
    if (metric === "turnoverTop" || metric === "volumeUp") return "volume";
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "neutral";
  }

  function valueText(value: number) {
    if (metric.includes("change")) return fmt(value, "%");
    if (metric === "volumeUp") return `${fmt(value)}×`;
    return fmt(value);
  }
</script>

<section
  class="rank-panel"
  id={panelId}
  role={panelId ? "tabpanel" : undefined}
  aria-labelledby={labelledBy}
  {hidden}
>
  <div class="rank-panel-header">
    <h2 id={headingId} class={metricClass()} title={metric === "volumeUp" ? volumeRatioHelp : undefined}>
      {label}
    </h2>
    <span>表示 {items.length}/{totalEligible}</span>
  </div>
  {#each items as item, index}
    <a class="rank-row" href={`/symbols/${encodeURIComponent(item.symbol)}?tf=${timeframe}`}>
      <small>{index + 1}位</small>
      <span title={item.symbol}>{formatDisplaySymbol(item.symbol)}</span>
      <strong class={valueClass(item.value)}>{valueText(item.value)}</strong>
    </a>
  {:else}
    <p class="empty">該当なし</p>
  {/each}
</section>

<style>
  .rank-panel {
    min-width: 0;
    border-right: 1px solid var(--line);
    background: var(--panel-solid);
    padding: 6px 8px;
    font-size: 12px;
    line-height: 1.12;
  }

  .rank-panel:last-child {
    border-right: 0;
  }

  .rank-panel-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    min-height: 16px;
  }

  .rank-panel-header span {
    color: var(--muted);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    white-space: nowrap;
  }

  h2 {
    margin: 0;
    color: var(--warning);
    font-size: 11px;
    line-height: 1.2;
  }

  h2.up { color: var(--up); }
  h2.down { color: var(--down); }
  h2.volume { color: var(--warning); }

  .rank-row {
    display: grid;
    grid-template-columns: 24px minmax(0, 1fr) minmax(88px, max-content);
    align-items: center;
    gap: 8px;
    min-height: 17px;
    width: 100%;
    padding: 0;
    border: 0;
    border-top: 1px solid color-mix(in srgb, var(--muted) 16%, transparent);
    background: transparent;
    color: inherit;
    cursor: pointer;
    text-decoration: none;
  }

  .rank-row:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }

  .rank-row:active { background: var(--panel-strong); }

  .rank-row small {
    color: var(--muted);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
    font-weight: 700;
    white-space: nowrap;
  }

  .rank-row span {
    overflow: hidden;
    min-width: 0;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rank-row strong {
    font-size: 11px;
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }

  strong.up { color: var(--up); }
  strong.down { color: var(--down); }
  strong.volume { color: var(--warning); }
  strong.neutral { color: var(--muted); }

  .empty { margin: 0; color: var(--subtle); }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .rank-row {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .rank-row:hover { color: var(--focus); }
  }

  @media (max-width: 560px) {
    .rank-panel {
      border-right: 0;
      padding-inline: var(--space-xs);
    }

    .rank-panel-header,
    .rank-row { gap: var(--space-xs); }

    .rank-row {
      grid-template-columns: minmax(20px, max-content) minmax(0, 1fr) minmax(44px, max-content);
    }

    .rank-row span {
      overflow: visible;
      overflow-wrap: anywhere;
      text-overflow: clip;
      white-space: normal;
    }
  }
</style>
