<script lang="ts">
  import { formatNumber as fmt } from "$lib/market/format";
  import type { RankingMetaValue, RankingTree } from "$lib/market/rankings";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";

  type RankingTimeframe = "5m" | "15m" | "1h" | "4h" | "24h" | "74h";
  type RankingMetric = readonly [label: string, metric: string];

  let {
    rankings,
    selectedTimeframe,
    timeframes,
    metrics,
    onTimeframeSelect
  }: {
    rankings: RankingTree | undefined;
    selectedTimeframe: RankingTimeframe;
    timeframes: readonly RankingTimeframe[];
    metrics: readonly RankingMetric[];
    onTimeframeSelect: (timeframe: RankingTimeframe) => void;
  } = $props();

  function metricTimeframe(metric: string): RankingTimeframe {
    return metric === "volumeUp" ? "15m" : selectedTimeframe;
  }

  function ranking(metric: string) {
    return rankings?.timeframes?.[metricTimeframe(metric)]?.[metric] ?? [];
  }

  function rankingMeta(metric: string): Required<Pick<RankingMetaValue, "limit" | "totalEligible">> {
    const items = ranking(metric);
    const meta = rankings?.meta?.timeframes?.[metricTimeframe(metric)]?.[metric];
    return {
      limit: meta?.limit ?? items.length,
      totalEligible: meta?.totalEligible ?? items.length
    };
  }

  function metricClass(metric: string) {
    if (metric === "changeUp") return "up";
    if (metric === "changeDown") return "down";
    if (metric === "turnoverTop" || metric === "volumeUp") return "volume";
    return "neutral";
  }

  function valueClass(metric: string, value: number) {
    if (metric === "turnoverTop" || metric === "volumeUp") return "volume";
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "neutral";
  }
</script>

<section class="ranking-area" aria-label={`${selectedTimeframe} ランキング`}>
  <div class="toolbar">
    <div>
      <h2>候補の動き</h2>
    </div>
    <div class="timeframe-strip" role="group" aria-label="時間軸">
      {#each timeframes as timeframe}
        <button
          type="button"
          class:active={selectedTimeframe === timeframe}
          aria-pressed={selectedTimeframe === timeframe}
          data-single-line-action
          onclick={() => onTimeframeSelect(timeframe)}
        >
          {timeframe}
        </button>
      {/each}
    </div>
  </div>
  <div class="rank-strip ranking-body">
    {#each metrics as [label, metric]}
      {@const items = ranking(metric)}
      {@const meta = rankingMeta(metric)}
      <section class="rank-panel">
        <div class="rank-panel-header">
          <h2 class={metricClass(metric)}>{label}</h2>
          <span>表示 {items.length}/{meta.totalEligible}</span>
        </div>
        {#each items as item, index}
          <a class="rank-row" href={`/symbols/${encodeURIComponent(item.symbol)}?tf=${metricTimeframe(metric)}`}>
            <small>{index + 1}位</small>
            <span title={item.symbol}>{formatDisplaySymbol(item.symbol)}</span>
            <strong class={valueClass(metric, item.value)}>{fmt(item.value, metric.includes("change") ? "%" : "")}</strong>
          </a>
        {:else}
          <p class="empty">該当なし</p>
        {/each}
      </section>
    {/each}
  </div>
</section>

<style>
  .ranking-area {
    border: 1px solid color-mix(in srgb, var(--muted) 22%, transparent);
    background: color-mix(in srgb, var(--bg-alt) 72%, transparent);
    box-shadow: none;
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px;
    border: 0;
    border-bottom: 1px solid var(--line);
    background: var(--panel-strong);
  }

  .toolbar h2 {
    margin: 0;
    font-size: 16px;
  }

  .timeframe-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .timeframe-strip button {
    min-height: 30px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: color-mix(in srgb, var(--panel-selected) 90%, transparent);
    color: var(--text);
    cursor: pointer;
    font: inherit;
    padding: 0 10px;
    white-space: nowrap;
  }

  .timeframe-strip button.active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
    font-weight: 800;
  }

  .timeframe-strip button:focus-visible,
  .rank-row:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }

  .timeframe-strip button:active,
  .rank-row:active {
    background: var(--panel-strong);
  }

  .timeframe-strip button.active:active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .rank-strip {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0;
    max-width: none;
    margin: 0;
  }

  .rank-panel {
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

  .rank-panel h2 {
    margin: 0;
    color: var(--warning);
    font-size: 11px;
    line-height: 1.2;
  }

  .rank-panel h2.up {
    color: var(--up);
  }

  .rank-panel h2.down {
    color: var(--down);
  }

  .rank-panel h2.volume {
    color: var(--warning);
  }

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

  .rank-row strong.up {
    color: var(--up);
  }

  .rank-row strong.down {
    color: var(--down);
  }

  .rank-row strong.volume {
    color: var(--warning);
  }

  .rank-row strong.neutral {
    color: var(--muted);
  }

  .empty {
    margin: 0;
    color: var(--subtle);
  }

  @media (max-width: 960px) {
    .ranking-area {
      box-sizing: border-box;
      width: 100%;
    }

    .ranking-body {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      max-block-size: min(48svh, 28rem);
      overflow-y: auto;
      overscroll-behavior-y: auto;
      touch-action: pan-y;
      scroll-padding-block: 4px;
      padding-block-end: 2px;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .timeframe-strip button,
    .rank-row {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .timeframe-strip button:hover,
    .rank-row:hover {
      border-color: var(--focus);
      color: var(--focus);
    }
  }

  @media (max-width: 560px) {
    .toolbar {
      align-items: stretch;
      flex-direction: column;
    }

    .ranking-body {
      grid-template-columns: minmax(0, 1fr);
    }

    .rank-panel {
      padding-inline: var(--space-xs);
    }

    .rank-panel-header,
    .rank-row {
      gap: var(--space-xs);
    }

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

  @media (max-width: 360px) {
    .timeframe-strip {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--space-sm);
    }

    .timeframe-strip button {
      width: 100%;
      padding-inline: 0;
    }
  }
</style>
