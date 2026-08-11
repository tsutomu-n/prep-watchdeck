<script lang="ts">
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import FontSelector from "$lib/components/FontSelector.svelte";
  import ThemeSelector from "$lib/components/ThemeSelector.svelte";
  import { formatNumber as fmt } from "$lib/market/format";
  import { abnormalDataQualityLabel, categoryLabel, changeTone, codeLabel, dataQualityClass } from "$lib/market/labels";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";

  let { row, selectedTimeframe }: { row: ScannerRowDTO; selectedTimeframe: string } = $props();
  let displaySymbol = $derived(formatDisplaySymbol(row.symbol));
  let qualityText = $derived(abnormalDataQualityLabel(row.dataQuality));

  function monitoringCategoryLabel(category: string) {
    return category === "NO_TRADE" ? "監視除外候補" : categoryLabel(category);
  }
</script>

<header class="symbol-top">
  <a class="back-link" href="/" data-sveltekit-reload data-single-line-action>一覧へ</a>
  <div class="symbol-title">
    <div>
      <h1 title={row.symbol}>{displaySymbol}</h1>
      <strong>{codeLabel(row.label)}</strong>
    </div>
    <div class="display-controls" aria-label="表示設定">
      <ThemeSelector />
      <FontSelector />
    </div>
  </div>
  <dl class="top-kpis">
    <div>
      <dt>score</dt>
      <dd>{fmt(row.attentionScore)}</dd>
    </div>
    <div>
      <dt>分類</dt>
      <dd>{monitoringCategoryLabel(row.category)}</dd>
    </div>
    {#if qualityText}
      <div>
        <dt>品質</dt>
        <dd class={`quality ${dataQualityClass(row.dataQuality)}`}>{qualityText}</dd>
      </div>
    {/if}
    <div>
      <dt>{selectedTimeframe}</dt>
      <dd class={`movement ${changeTone(row.changePctByTf?.[selectedTimeframe])}`}>
        {fmt(row.changePctByTf?.[selectedTimeframe], "%")}
      </dd>
    </div>
  </dl>
</header>

<style>
  .symbol-top {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) minmax(440px, 0.75fr);
    align-items: stretch;
    gap: 0;
    max-width: 1440px;
    margin: 0 auto 8px;
    border: 1px solid var(--line);
    background: var(--panel);
  }

  .back-link,
  .symbol-title,
  .top-kpis {
    border: 0;
    background: transparent;
  }

  .back-link {
    display: grid;
    place-items: center;
    min-width: 80px;
    padding: 0 12px;
    color: var(--focus);
    font-weight: 800;
    text-decoration: none;
    white-space: nowrap;
    border-right: 1px solid var(--line);
  }

  .back-link:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }

  .back-link:active {
    background: var(--panel-strong);
  }

  .symbol-title {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: var(--space-md);
    min-width: 0;
    padding: 10px 12px;
    border-right: 1px solid var(--line);
  }

  .symbol-title h1 {
    margin: 0;
    overflow-wrap: anywhere;
    font-size: clamp(30px, 5vw, 64px);
    line-height: 0.92;
  }

  .symbol-title strong {
    display: block;
    margin-top: 5px;
    color: var(--warning);
    font-size: 14px;
  }

  .display-controls {
    display: grid;
    align-content: center;
    gap: var(--space-xs);
    min-width: 0;
  }

  .top-kpis {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0;
    margin: 0;
    background: transparent;
  }

  .top-kpis div {
    min-width: 0;
    padding: 10px;
    border-left: 1px solid var(--line);
    background: transparent;
  }

  .top-kpis div:first-child {
    border-left: 0;
  }

  dt {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
  }

  dd {
    margin: 5px 0 0;
    font-size: 20px;
    font-weight: 850;
    overflow-wrap: anywhere;
  }

  .movement.good {
    color: var(--up);
  }

  .movement.risk {
    color: var(--down);
  }

  .quality.good {
    color: var(--quality-good);
  }

  .quality.risk {
    color: var(--quality-risk);
  }

  @media (max-width: 1080px) {
    .symbol-top {
      grid-template-columns: 1fr;
    }

    .top-kpis {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .back-link,
    .symbol-title {
      border-right: 0;
      border-bottom: 1px solid var(--line);
    }

    .top-kpis div {
      border-left: 0;
    }

    .top-kpis div:nth-child(even) {
      border-left: 1px solid var(--line);
    }

    .top-kpis div:nth-child(n + 3) {
      border-top: 1px solid var(--line);
    }
  }

  @media (max-width: 560px) {
    .symbol-title {
      display: grid;
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .back-link {
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .back-link:hover {
      background: var(--panel-strong);
    }
  }
</style>
