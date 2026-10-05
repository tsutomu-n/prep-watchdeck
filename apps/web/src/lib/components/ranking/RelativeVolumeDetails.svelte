<script lang="ts">
  import type { RankedRow } from "$lib/generated/ranking-response";
  import { indicatorLabel, rankingTimestamp } from "$lib/market/ranking";
  import { DEFAULT_TURNOVER_DECIMALS, formatTurnover } from "$lib/market/turnover-format";

  let { row, expired = false, decimals = DEFAULT_TURNOVER_DECIMALS }: {
    row: RankedRow; expired?: boolean; decimals?: number;
  } = $props();
  const comparison = $derived(row.turnoverComparison);
  const samples = $derived([
    ["一昨日", comparison.twoDaysAgo], ["昨日", comparison.previousDay], ["現在", comparison.current]
  ] as const);
</script>

<section class="volume-details" aria-label="売買代金の過去日比較" data-testid="relative-volume-details">
  <h3>売買代金の過去日比較 <span>USDT</span></h3>
  {#if expired}<p class="expired">更新停止・過去時点の比較です。</p>{/if}
  <dl class="day-windows">
    {#each samples as [label, sample]}
      <div>
        <dt>{label}<small>{rankingTimestamp(sample.anchor)}<br />〜 {rankingTimestamp(sample.cutoff)} JST</small></dt>
        <dd>
          {sample.status === "ready" && sample.quoteTurnover !== null ? formatTurnover(sample.quoteTurnover, decimals)
            : indicatorLabel({ status: sample.status, value: null }, "倍")}
        </dd>
      </div>
    {/each}
  </dl>
  <dl class="day-ratios">
    <div><dt>昨日比</dt><dd>{indicatorLabel(comparison.previousDayRatio, "倍")}</dd></div>
    <div><dt>一昨日比</dt><dd>{indicatorLabel(comparison.twoDaysAgoRatio, "倍")}</dd></div>
  </dl>
</section>

<style>
  .volume-details { padding: var(--space-sm) 0; border-block: 1px solid var(--line); margin-bottom: var(--space-sm); }
  h3 { margin: 0 0 var(--space-sm); font-size: var(--type-body-sm-size); color: var(--text); }
  h3 span { color: var(--muted); font-size: var(--type-label-caps-size); font-weight: 500; margin-left: var(--space-xs); }
  dl { margin: 0; }dd { margin: var(--space-xs) 0 0; font-variant-numeric: tabular-nums; color: var(--text); overflow-wrap: anywhere; }
  .day-windows { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-sm); font-size: var(--type-body-sm-size); }
  dt { color: var(--subtle); }small { display: block; font-size: var(--type-label-caps-size); color: var(--muted); line-height: 1.6; font-variant-numeric: tabular-nums; }
  .day-ratios { display: flex; flex-wrap: wrap; gap: var(--space-sm) var(--space-lg); font-size: var(--type-body-sm-size); padding-top: var(--space-sm); }
  .day-ratios div { display: flex; gap: var(--space-sm); }.day-ratios dd { margin: 0; }
  .expired { color: var(--warning); font-size: var(--type-body-sm-size); }
</style>
