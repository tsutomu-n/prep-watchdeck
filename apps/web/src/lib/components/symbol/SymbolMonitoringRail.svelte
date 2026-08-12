<script lang="ts">
  import SymbolChip from "$lib/components/symbol/SymbolChip.svelte";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import {
    abnormalDataQualityLabel,
    activityPhaseLabel,
    categoryLabel,
    codeLabel,
    dataQualityClass,
    openInterestStateLabel
  } from "$lib/market/labels";
  import type { MovementSignal } from "$lib/market/row-analysis";

  let {
    row,
    selectedTimeframe,
    selectedSignals
  }: {
    row: ScannerRowDTO;
    selectedTimeframe: string;
    selectedSignals: MovementSignal[];
  } = $props();
  let qualityText = $derived(abnormalDataQualityLabel(row.dataQuality));

  function monitoringCategoryLabel(category: string) {
    return category === "NO_TRADE" ? "監視除外候補" : categoryLabel(category);
  }
</script>

<aside id="symbol-monitoring" class="monitoring-rail" aria-label="監視材料" tabindex="-1">
  <section class="rail-card overview">
    <h2>監視材料</h2>
    <dl class="monitoring-summary">
      <div>
        <dt>分類</dt>
        <dd>{monitoringCategoryLabel(row.category)}</dd>
      </div>
      <div>
        <dt>ラベル</dt>
        <dd>{codeLabel(row.label)}</dd>
      </div>
      {#if qualityText}
        <div>
          <dt>品質</dt>
          <dd class={`quality ${dataQualityClass(row.dataQuality)}`}>{qualityText}</dd>
        </div>
      {/if}
      <div>
        <dt>時間軸</dt>
        <dd>{selectedTimeframe}</dd>
      </div>
      <div>
        <dt>OI 60分</dt>
        <dd>{openInterestStateLabel(row.openInterestState)}</dd>
      </div>
      <div>
        <dt>活動phase</dt>
        <dd>{activityPhaseLabel(row.activityPhase)}</dd>
      </div>
    </dl>
  </section>

  <section class="rail-card">
    <h2>即時シグナル</h2>
    <div class="chips">
      {#each selectedSignals as signal}
        <SymbolChip tone={signal.tone}>{signal.label}</SymbolChip>
      {:else}
        <SymbolChip>目立つ方向差なし</SymbolChip>
      {/each}
      {#each row.riskTagCodes ?? [] as code}
        <SymbolChip tone="warn">{codeLabel(code)}</SymbolChip>
      {:else}
        <SymbolChip>強い警戒なし</SymbolChip>
      {/each}
    </div>
  </section>
</aside>

<style>
  .monitoring-rail {
    display: grid;
    gap: 0;
    border: 1px solid var(--line-strong);
    border-left-width: 3px;
    background: var(--panel-selected);
  }

  .rail-card {
    padding: 12px;
    border-bottom: 1px solid var(--line);
  }

  .rail-card:last-child {
    border-bottom: 0;
  }

  .rail-card h2 {
    margin: 0;
  }

  .rail-card h2 {
    font-size: 15px;
  }

  .monitoring-summary {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    margin: 10px 0 0;
    border-top: 1px solid var(--line);
    background: transparent;
  }

  .monitoring-summary div {
    min-width: 0;
    padding: 10px;
    background: transparent;
  }

  .monitoring-summary div:nth-child(even) {
    border-left: 1px solid var(--line);
  }

  .monitoring-summary div:nth-child(n + 3) {
    border-top: 1px solid var(--line);
  }

  dt {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
  }

  dd {
    margin: 5px 0 0;
    overflow-wrap: anywhere;
    font-size: 15px;
    font-weight: 850;
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 10px;
  }

  .quality.good {
    color: var(--quality-good);
  }

  .quality.risk {
    color: var(--quality-risk);
  }
</style>
