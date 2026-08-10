<script lang="ts">
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { ATTENTION_SCORE_HELP_TEXT, ATTENTION_SCORE_LABEL } from "$lib/market/attention-score";
  import { formatNumber as fmt } from "$lib/market/format";
  import { categoryLabel, codeLabel, dataQualityLabel, rowExclusionLabels } from "$lib/market/labels";
  import { movementSignals, type Range24h } from "$lib/market/row-analysis";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";

  let {
    row,
    selectedTimeframe,
    range,
    volumeRatioBaseline,
    volumeRatioHelp
  }: {
    row: ScannerRowDTO;
    selectedTimeframe: string;
    range: Range24h | null;
    volumeRatioBaseline: string;
    volumeRatioHelp: string;
  } = $props();

  let selectedSignals = $derived(movementSignals(row, selectedTimeframe));
  let exclusionItems = $derived(rowExclusionLabels(row));
  let displaySymbol = $derived(formatDisplaySymbol(row.symbol));
  let volumeRatio = $derived(row.volumeRatioByTf?.["15m"]);
  let volumeRatioText = $derived(
    typeof volumeRatio === "number" && Number.isFinite(volumeRatio)
      ? `${fmt(volumeRatio)}×`
      : "—"
  );
</script>

<div class="section-head">
  <h2 title={row.symbol}>{displaySymbol}</h2>
  <div class="section-actions">
    <span>{categoryLabel(row.category)}</span>
    <a
      class="analysis-link"
      href={`/symbols/${encodeURIComponent(row.symbol)}?tf=${selectedTimeframe}`}
      aria-label={`${row.symbol} の個別分析を開く`}
      data-single-line-action
    >
      個別分析
    </a>
  </div>
</div>
<section class="detail-hero" aria-label="選択銘柄サマリー">
  <div>
    <strong>{codeLabel(row.label)}</strong>
  </div>
  <dl>
    <div>
      <dt>{ATTENTION_SCORE_LABEL}</dt>
      <dd>{fmt(row.attentionScore)}</dd>
    </div>
    <div>
      <dt>データ品質</dt>
      <dd>{dataQualityLabel(row.dataQuality)}</dd>
    </div>
    <div>
      <dt>{selectedTimeframe}</dt>
      <dd>{fmt(row.changePctByTf?.[selectedTimeframe], "%")}</dd>
    </div>
  </dl>
  <p class="attention-note">{ATTENTION_SCORE_HELP_TEXT}</p>
</section>
<section class="precheck" aria-label="監視材料">
  <div>
    <h3>確認</h3>
    <div class="signal-list">
      {#each selectedSignals as signal}
        <span class={`signal-chip ${signal.tone}`}>{signal.label}</span>
      {:else}
        <span class="signal-chip neutral">目立つ方向差なし</span>
      {/each}
    </div>
  </div>
  <div>
    <h3>警戒</h3>
    <div class="signal-list">
      {#each row.riskTagCodes ?? [] as code}
        <span class="signal-chip warn">{codeLabel(code)}</span>
      {:else}
        <span class="signal-chip neutral">強い警戒なし</span>
      {/each}
    </div>
  </div>
</section>
{#if exclusionItems.length > 0}
  <section class="exclusion-panel" aria-label="除外理由">
    <div class="section-head compact">
      <h3>{row.category === "NO_TRADE" ? "除外理由" : "注意理由"}</h3>
      <span>{dataQualityLabel(row.dataQuality)}</span>
    </div>
    <div class="signal-list">
      {#each exclusionItems as reason}
        <span class="signal-chip warn">{reason}</span>
      {/each}
    </div>
    <p>監視を続ける条件と解除条件を先に言語化する。</p>
  </section>
{/if}
<dl class="stats">
  <div>
    <dt title={volumeRatioHelp}>15m量倍率</dt>
    <dd>{volumeRatioText}</dd>
    <small title={volumeRatioHelp}>{volumeRatioBaseline}</small>
  </div>
  <div>
    <dt>15分変化率</dt>
    <dd>{fmt(row.changePctByTf?.["15m"], "%")}</dd>
  </div>
  <div>
    <dt>1時間売買代金</dt>
    <dd>{fmt(row.turnoverUsdtByTf?.["1h"])}</dd>
  </div>
  <div>
    <dt>74時間価格変化</dt>
    <dd>{fmt(row.priceChange74hPct, "%")}</dd>
  </div>
  <div>
    <dt>データ網羅率</dt>
    <dd>{fmt((row.coverageRatio ?? 0) * 100, "%")}</dd>
  </div>
  <div>
    <dt>24hレンジ位置</dt>
    <dd>{range ? fmt(range.positionPct, "%") : "未取得"}</dd>
  </div>
  <div>
    <dt>24hレンジ幅</dt>
    <dd>{range ? fmt(range.rangePct, "%") : "未取得"}</dd>
  </div>
</dl>

<style>
  h2,
  h3,
  p {
    margin: 0;
  }

  .section-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    min-height: var(--control-height-primary-touch);
    padding: 0 var(--space-md);
    border-bottom: 1px solid var(--line-strong);
    border-color: var(--line);
    background: var(--panel-strong);
  }

  .section-head h2 {
    font-size: var(--type-heading-md-size);
    font-weight: var(--type-heading-md-weight);
    line-height: var(--type-heading-md-leading);
  }

  .section-head span {
    color: var(--focus);
    font-size: var(--type-body-sm-size);
  }

  .section-actions {
    display: flex;
    align-items: center;
    gap: var(--space-md);
  }

  .analysis-link {
    display: inline-flex;
    align-items: center;
    color: var(--text);
    font-size: var(--type-body-sm-size);
    font-weight: 800;
    text-decoration-color: var(--focus);
    text-underline-offset: 3px;
    white-space: nowrap;
  }

  .analysis-link:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  .analysis-link:active {
    color: var(--focus);
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .section-head {
      flex-wrap: wrap;
      gap: var(--space-sm) var(--space-md);
      padding-block: var(--space-sm);
    }

    .analysis-link {
      min-width: 44px;
      min-height: 48px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .analysis-link:hover {
      color: var(--focus);
    }
  }

  .section-head.compact {
    min-height: auto;
    padding: 0;
    border-bottom: 0;
    background: transparent;
  }

  .detail-hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(190px, 0.9fr);
    gap: var(--space-md);
    padding: var(--space-lg) var(--space-md);
    border-bottom: 1px solid var(--line);
    background: transparent;
  }

  .attention-note {
    grid-column: 1 / -1;
    color: var(--subtle);
    font-size: 12px;
    line-height: 1.4;
  }

  .detail-hero strong {
    display: block;
    margin-top: 5px;
    color: var(--text);
    font-size: 18px;
    line-height: 1.25;
  }

  .detail-hero dl {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1px;
    margin: 0;
    background: transparent;
  }

  .detail-hero div {
    min-width: 0;
  }

  .detail-hero dl div {
    padding: 8px;
    border-left: 1px solid var(--line);
    background: transparent;
  }

  .detail-hero dt {
    font-size: 10px;
    text-transform: uppercase;
  }

  .detail-hero dd {
    margin-top: 4px;
    font-size: 16px;
  }

  .precheck,
  .exclusion-panel {
    padding: 12px;
    border-bottom: 1px solid var(--line-strong);
    background: transparent;
  }

  .precheck {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    border-top: 1px solid var(--warning-border);
  }

  .precheck h3,
  .exclusion-panel h3 {
    font-size: 12px;
    color: var(--subtle);
  }

  .precheck .signal-list {
    margin-top: 8px;
  }

  .exclusion-panel {
    border-top: 1px solid var(--warning-border);
    background: color-mix(in srgb, var(--warning) 12%, var(--surface));
  }

  .exclusion-panel p {
    margin-top: 8px;
    color: var(--warning);
    font-size: 12px;
  }

  .stats {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0;
    margin: 0;
    background: transparent;
  }

  .stats div {
    padding: 12px;
    border-bottom: 1px solid var(--line);
    background: transparent;
  }

  dt {
    color: var(--subtle);
    font-size: 12px;
  }

  dd {
    margin: 6px 0 0;
    overflow-wrap: anywhere;
    font-size: 18px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
  }

  .stats small {
    display: block;
    margin-top: 4px;
    color: var(--muted);
    font-size: 10px;
    line-height: 1.3;
  }

  .signal-list {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
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

  @media (max-width: 560px) {
    .detail-hero {
      grid-template-columns: 1fr;
    }

    .precheck {
      grid-template-columns: 1fr;
    }
  }
</style>
