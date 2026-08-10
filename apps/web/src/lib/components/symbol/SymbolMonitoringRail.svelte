<script lang="ts">
  import SymbolChip from "$lib/components/symbol/SymbolChip.svelte";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { formatNumber as fmt } from "$lib/market/format";
  import {
    categoryLabel,
    codeLabel,
    dataQualityClass,
    dataQualityLabel,
    openInterestStateLabel
  } from "$lib/market/labels";
  import type { RankingPositionResult } from "$lib/market/rankings";
  import type { MovementSignal } from "$lib/market/row-analysis";

  type RankingContextItem = {
    id: string;
    label: string;
    result: RankingPositionResult | null;
  };

  let {
    row,
    selectedTimeframe,
    rankingContext,
    selectedSignals
  }: {
    row: ScannerRowDTO;
    selectedTimeframe: string;
    rankingContext: RankingContextItem[];
    selectedSignals: MovementSignal[];
  } = $props();

  function rankingValueLabel(item: RankingContextItem) {
    if (!item.result || item.result.value === null) return "";
    return fmt(item.result.value, item.id.includes("change") ? "%" : "");
  }

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
      <div>
        <dt>品質</dt>
        <dd class={`quality ${dataQualityClass(row.dataQuality)}`}>{dataQualityLabel(row.dataQuality)}</dd>
      </div>
      <div>
        <dt>時間軸</dt>
        <dd>{selectedTimeframe}</dd>
      </div>
      <div>
        <dt>OI 60分</dt>
        <dd>{openInterestStateLabel(row.openInterestState)}</dd>
      </div>
    </dl>
  </section>

  <section class="rail-card">
    <h2>ランキング位置</h2>
    <p class="rank-hint">選択時間軸の掲載範囲</p>
    <dl class="rank-context">
      {#each rankingContext as item}
        <div class:rank-missing={!item.result || item.result.rank === null}>
          <dt>{item.label}</dt>
          <dd>
            {#if item.result?.rank !== null && item.result?.rank !== undefined}
              <span class="rank-main">{item.result.totalEligible}件中 {item.result.rank}位</span>
              <span class="rank-sub">{rankingValueLabel(item)}</span>
            {:else if item.result}
              <span class="rank-main">上位{item.result.limit}外</span>
              <span class="rank-sub">対象{item.result.totalEligible}件</span>
            {:else}
              <span class="rank-main">ランキングなし</span>
              <span class="rank-sub">ランキング未掲載</span>
            {/if}
          </dd>
        </div>
      {/each}
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

  .rail-card h2,
  .rail-card p {
    margin: 0;
  }

  .rail-card h2 {
    font-size: 15px;
  }

  .rank-hint {
    margin-top: 5px;
    color: var(--muted);
    font-size: 11px;
    line-height: 1.35;
  }

  .monitoring-summary,
  .rank-context {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    margin: 10px 0 0;
    border-top: 1px solid var(--line);
    background: transparent;
  }

  .monitoring-summary div,
  .rank-context div {
    min-width: 0;
    padding: 10px;
    background: transparent;
  }

  .monitoring-summary div:nth-child(even),
  .rank-context div:nth-child(even) {
    border-left: 1px solid var(--line);
  }

  .monitoring-summary div:nth-child(n + 3),
  .rank-context div:nth-child(n + 3) {
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

  .rank-main,
  .rank-sub {
    display: block;
  }

  .rank-sub {
    margin-top: 3px;
    color: var(--subtle);
    font-size: 11px;
    font-weight: 700;
    line-height: 1.25;
  }

  .rank-missing .rank-main,
  .rank-missing .rank-sub {
    color: var(--muted);
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
