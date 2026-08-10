<script lang="ts">
  import DashboardMiniSparkline from "$lib/components/dashboard/DashboardMiniSparkline.svelte";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { formatCompactNumber as fmtCompact, formatNumber as fmt } from "$lib/market/format";
  import {
    categoryCompactLabel,
    categoryLabel,
    changeTone,
    codeLabel,
    dataQualityLabel,
    rowQualityClass as qualityClass
  } from "$lib/market/labels";
  import { movementSignals } from "$lib/market/row-analysis";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import type { TickerOverlay } from "$lib/market/ticker-overlay.svelte";

  let {
    row,
    tickerOverlay,
    selectedSymbol,
    selectedTimeframe,
    rankingTimeframes,
    noteBadge,
    volumeRatioHelp,
    isRekindle,
    tabIndex,
    onSymbolSelect,
    onRowFocus,
    onRowKeydown
  }: {
    row: ScannerRowDTO;
    tickerOverlay: TickerOverlay;
    selectedSymbol: string | null;
    selectedTimeframe: string;
    rankingTimeframes: readonly string[];
    noteBadge: string | null;
    volumeRatioHelp: string;
    isRekindle: boolean;
    tabIndex: 0 | -1;
    onSymbolSelect: (symbol: string) => void;
    onRowFocus: (symbol: string) => void;
    onRowKeydown: (symbol: string, event: KeyboardEvent) => void;
  } = $props();

  let signals = $derived(movementSignals(row, selectedTimeframe));
  let displaySymbol = $derived(formatDisplaySymbol(row.symbol));
  let volumeRatio15m = $derived(row.volumeRatioByTf?.["15m"]);
  let volumeRatioText = $derived(
    typeof volumeRatio15m === "number" && Number.isFinite(volumeRatio15m)
      ? `${fmt(volumeRatio15m)}×`
      : "—"
  );
  let price = $derived(tickerOverlay.priceFor(row.symbol, row.lastPrice, row.analysisPrice));
  let priceDescriptionId = $derived(`market-row-price-${encodeURIComponent(row.symbol)}`);
  let accessibleSummary = $derived(
    [
      `${row.symbol} を選択`,
      `分類 ${categoryLabel(row.category)}`,
      `ラベル ${codeLabel(row.label)}`,
      `時間軸別変化 ${rankingTimeframes
        .map((timeframe) => `${timeframe} ${fmtCompact(row.changePctByTf?.[timeframe], "%")}`)
        .join("、")}`,
      `${selectedTimeframe}変化 ${fmtCompact(row.changePctByTf?.[selectedTimeframe], "%")}`,
      `${selectedTimeframe}代金 ${fmtCompact(row.turnoverUsdtByTf?.[selectedTimeframe])}`,
      `15分量倍率 ${volumeRatioText}`,
      `品質 ${dataQualityLabel(row.dataQuality)}`,
      noteBadge ? `注記 ${noteBadge}` : null,
      signals.length > 0
        ? `シグナル ${signals.map((signal) => signal.label).join("、")}`
        : null
    ]
      .filter((item): item is string => item !== null)
      .join("。")
  );
</script>

<div
  class:selected={selectedSymbol === row.symbol}
  class="market-row"
  data-market-row
  data-symbol={row.symbol}
>
  <button
    type="button"
    class="row-select"
    data-row-select
    data-symbol={row.symbol}
    aria-label={accessibleSummary}
    aria-describedby={priceDescriptionId}
    aria-pressed={selectedSymbol === row.symbol}
    tabindex={tabIndex}
    onfocus={() => onRowFocus(row.symbol)}
    onkeydown={(event) => onRowKeydown(row.symbol, event)}
    onclick={() => onSymbolSelect(row.symbol)}
  >
    <span class="symbol" title={row.symbol}>{displaySymbol}</span>
    <span
      id={priceDescriptionId}
      class:stale={price.stale}
      class="current-price"
      data-price-source={price.source}
      title={`${fmtCompact(price.value)}、${price.stale ? "Hot価格: 5秒超更新なし" : `価格source: ${price.source}`}`}
    >
      <span>{fmtCompact(price.value)}</span>
      {#if price.stale}<small>STALE</small>{/if}
    </span>
    <DashboardMiniSparkline {row} {selectedTimeframe} />
    <span class="label" title={codeLabel(row.label)}>
      <span><small class="category">{categoryCompactLabel(row.category)} · </small>{codeLabel(row.label)}</span>
      {#if signals.length > 0}
        <span class="row-signals">
          {#each signals as signal}
            <span
              class={`signal-chip ${signal.tone}`}
              aria-label={signal.label}
              title={signal.label}
            >{signal.shortLabel}</span>
          {/each}
        </span>
      {/if}
    </span>
    <span class="volume-ratio" title={`15分量倍率 ${volumeRatioText}。${volumeRatioHelp}`}
      >{volumeRatioText}</span
    >
    {#each rankingTimeframes as timeframe, index}
      <span
        class={`tf-metric ${changeTone(row.changePctByTf?.[timeframe])}`}
        style={`grid-area: tf${index}`}
      >
        {fmtCompact(row.changePctByTf?.[timeframe], "%")}
      </span>
    {/each}
    {#if noteBadge}
      <span class:rekindle={isRekindle} class="note-badge" aria-label={noteBadge} title={noteBadge}
        >{noteBadge}</span
      >
    {:else}
      <span class="note-badge placeholder" aria-hidden="true"></span>
    {/if}
    <span class={qualityClass(row)}>{dataQualityLabel(row.dataQuality)}</span>
    <span class="tf-change" title={`${selectedTimeframe}変化 ${fmtCompact(row.changePctByTf?.[selectedTimeframe], "%")}`}
      >{fmtCompact(row.changePctByTf?.[selectedTimeframe], "%")}</span
    >
    <span class="tf-volume" title={`${selectedTimeframe}代金 ${fmtCompact(row.turnoverUsdtByTf?.[selectedTimeframe])}`}
      >{fmtCompact(row.turnoverUsdtByTf?.[selectedTimeframe])}</span
    >
  </button>
</div>

<style>
  /* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4
   * component: market row · genre: project-locked technical · theme: DESIGN.md
   * states: default · hover · focus · active · selected
   * contrast: pass (40–41) · tokens: pass (48) · responsive: pass (34, 49–57)
   */
  .market-row {
    min-width: 0;
    min-height: var(--row-height-desktop);
    content-visibility: auto;
    contain-intrinsic-size: auto var(--row-height-desktop);
  }

  .market-row.selected,
  .market-row:focus-within {
    content-visibility: visible;
  }

  .row-select {
    display: grid;
    grid-template-columns:
      minmax(80px, 0.55fr)
      minmax(78px, 0.55fr)
      84px
      minmax(112px, 0.85fr)
      44px
      repeat(6, 46px)
      minmax(68px, 0.5fr)
      42px
      56px;
    grid-template-areas: "symbol price spark label score tf0 tf1 tf2 tf3 tf4 tf5 volume quality badge";
    align-items: center;
    gap: 0 10px;
    box-sizing: border-box;
    width: 100%;
    min-width: 0;
    min-height: var(--row-height-desktop);
    border: 0;
    border-top: 1px solid color-mix(in srgb, var(--muted) 15%, transparent);
    background: transparent;
    padding: 0 var(--space-md);
    color: inherit;
    cursor: pointer;
    font: inherit;
    text-align: left;
    text-decoration: none;
  }

  .market-row.selected .row-select {
    background: var(--panel-selected);
    box-shadow: inset 3px 0 0 var(--focus);
  }

  @media (hover: hover) and (pointer: fine) {
    .row-select:hover {
      background: var(--surface);
    }

    .market-row.selected .row-select:hover {
      background: var(--panel-selected);
    }
  }

  @media (any-pointer: coarse) {
    .market-row,
    .row-select {
      min-height: var(--control-height-touch);
    }
  }

  .row-select:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
    background: var(--surface);
  }

  .market-row.selected .row-select:focus-visible {
    background: var(--panel-selected);
  }

  .row-select:active {
    border-top-color: var(--line-strong);
    background: var(--panel-strong);
  }

  .market-row.selected .row-select:active {
    background: var(--panel-selected);
  }

  .symbol {
    grid-area: symbol;
    min-width: 0;
    overflow: hidden;
    font-weight: 800;
    letter-spacing: 0;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .current-price {
    grid-area: price;
    display: grid;
    justify-items: end;
    min-width: 0;
    color: var(--text);
    font-size: var(--type-body-sm-size);
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    line-height: 1.05;
  }

  .current-price > span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .current-price small {
    color: var(--quality-risk);
    font-size: 8px;
    font-weight: 800;
  }

  .current-price.stale > span {
    color: var(--quality-risk);
  }

  .label,
  .category {
    color: var(--subtle);
  }

  .label {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    grid-area: label;
    gap: var(--space-xs);
    min-width: 0;
  }

  .label > span:first-child {
    flex: 1 1 0;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row-signals {
    display: inline-flex;
    flex: 0 0 auto;
    flex-wrap: nowrap;
    gap: var(--space-xxs);
    margin-left: 0;
    vertical-align: middle;
  }

  .signal-chip {
    display: inline-flex;
    align-items: center;
    min-height: 18px;
    border: 0;
    padding: 1px 0;
    color: var(--chip-neutral);
    font-size: 10px;
    line-height: 1.2;
    white-space: nowrap;
  }

  .signal-chip.up {
    color: var(--up);
  }

  .signal-chip.down {
    color: var(--down);
  }

  .signal-chip.warn {
    color: var(--warning);
  }

  .signal-chip.neutral {
    color: var(--chip-neutral);
  }

  .category {
    display: inline;
    flex: 0 0 auto;
    color: var(--subtle);
    font-size: var(--type-label-caps-size);
    font-weight: 800;
  }

  .note-badge {
    grid-area: badge;
    display: block;
    border: 1px solid var(--chip-line);
    padding: 3px 4px;
    color: var(--chip-neutral);
    font-size: 10px;
    text-align: center;
    overflow-wrap: anywhere;
  }

  .note-badge.rekindle {
    border-color: var(--warning-border);
    color: var(--warning);
  }

  .note-badge.placeholder {
    display: none;
    border-color: transparent;
  }

  .volume-ratio {
    grid-area: score;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .ok,
  .risk {
    grid-area: quality;
    display: block;
    text-align: right;
    font-size: var(--type-label-caps-size);
  }

  .ok {
    color: var(--quality-good);
  }

  .risk {
    color: var(--quality-risk);
  }

  .tf-change {
    display: none;
    grid-area: change;
    text-align: right;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
  }

  .tf-metric {
    text-align: right;
    font-size: var(--type-data-md-size);
    font-weight: var(--type-data-md-weight);
    font-variant-numeric: tabular-nums;
  }

  .tf-metric.good {
    color: var(--up);
  }

  .tf-metric.risk {
    color: var(--down);
  }

  .tf-metric.neutral {
    color: var(--muted);
  }

  .tf-volume {
    grid-area: volume;
    overflow: hidden;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  @container watchlist (max-width: 62.124rem) {
    .market-row {
      contain-intrinsic-size: auto var(--row-height-mobile);
      min-height: var(--row-height-mobile);
    }

    .row-select {
      grid-template-columns: minmax(0, 1fr) 72px minmax(48px, 56px) 56px;
      grid-template-areas:
        "symbol spark score quality"
        "price spark change badge"
        "label label volume volume";
      column-gap: var(--space-sm);
      row-gap: var(--space-xs);
      min-height: var(--row-height-mobile);
      padding-inline: var(--space-sm);
    }

    .tf-metric {
      display: none;
    }

    .tf-change {
      display: block;
    }

  }
</style>
