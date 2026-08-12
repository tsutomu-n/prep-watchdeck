<script lang="ts">
  import SelectedSymbolDetailGroup from "$lib/components/dashboard/SelectedSymbolDetailGroup.svelte";
  import { formatDateTime, formatMarketPrice, formatNumber } from "$lib/market/format";
  import type {
    PerpVenueComparisonItem,
    PerpVenueSource
  } from "$lib/market/perp-venue-comparison";

  let { item }: { item: PerpVenueComparisonItem } = $props();

  const percentFormatter = new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 6,
    signDisplay: "auto"
  });

  function venueLabel(venue: PerpVenueSource["venue"]): string {
    return venue === "bitget" ? "Bitget" : "Hyperliquid";
  }

  function formatRate(value: number | null): string {
    return value === null ? "比較不能" : `${percentFormatter.format(value * 100)}%`;
  }

  function formatNotional(value: number | null, quote: string): string {
    return value === null ? "比較不能" : `${formatNumber(value)} ${quote}`;
  }

  function statusBadge(): string {
    const valid = item.sources.filter((source) => source.status === "ok").length;
    return `${valid}/2`;
  }
</script>

<SelectedSymbolDetailGroup
  group="perp-venue-comparison"
  title="Bitget / Hyperliquid Perp比較"
  description="価格 / Funding / OI / 24h出来高"
  badge={statusBadge()}
  tone={item.status === "ready" ? "good" : item.status === "partial" ? "warn" : "risk"}
>
  <section class="venue-comparison" aria-label="選択銘柄 Perp会場比較">
    <header>
      <div>
        <strong>{item.asset}</strong>
        <small>同名・標準Core・暗号資産Perpだけを参考比較</small>
      </div>
      <span>{item.markSpreadPct === null ? "価格差 比較不能" : `価格差 ${formatRate(item.markSpreadPct / 100)}`}</span>
    </header>

    <div class="venues">
      {#each item.sources as source}
        <article class:unavailable={source.status === "unavailable"}>
          <div class="venue-head">
            <h3>{venueLabel(source.venue)}</h3>
            <span>{source.sourceSymbol}</span>
          </div>
          <p class="contract">価格 {source.quote} / 証拠金 {source.collateral}</p>
          {#if source.status === "ok"}
            <dl>
              <div>
                <dt>Mark price</dt>
                <dd>{formatMarketPrice(source.markPrice)} {source.quote}</dd>
              </div>
              <div>
                <dt>Funding</dt>
                <dd>{formatRate(source.fundingRate)} / {source.fundingIntervalHours}h</dd>
                <small>1h換算 {formatRate(source.fundingRatePerHour)}</small>
              </div>
              <div>
                <dt>建玉想定元本</dt>
                <dd>{formatNotional(source.openInterestNotional, source.quote)}</dd>
                <small>基軸数量 {formatNumber(source.openInterestBase)}</small>
              </div>
              <div>
                <dt>24h出来高</dt>
                <dd>{formatNotional(source.volume24hNotional, source.quote)}</dd>
              </div>
            </dl>
            <time datetime={new Date(source.observedAt ?? 0).toISOString()}>
              観測 {formatDateTime(source.observedAt ?? 0)}
            </time>
          {:else}
            <p class="source-error">取得不能: {source.error ?? "unknown"}</p>
          {/if}
        </article>
      {/each}
    </div>

    <p class="caveat">
      USDTとUSDCを同一通貨へ換算していません。会場別の監視値であり、売買・裁定判断には使いません。
    </p>
  </section>
</SelectedSymbolDetailGroup>

<style>
  .venue-comparison {
    background: var(--panel);
  }

  header,
  .venue-head {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-sm);
  }

  header {
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  header strong,
  header small {
    display: block;
  }

  header strong,
  .venue-head h3 {
    margin: 0;
    color: var(--text);
    font-size: 12px;
  }

  header small,
  header span,
  .contract,
  time,
  dl small,
  .caveat {
    color: var(--muted);
    font-size: 9px;
    line-height: 1.4;
  }

  header span {
    flex: 0 0 auto;
    color: var(--chip-neutral);
    white-space: nowrap;
  }

  .venues {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1px;
    background: var(--line);
  }

  article {
    min-width: 0;
    padding: var(--space-sm);
    background: var(--panel-strong);
  }

  article.unavailable h3,
  .source-error {
    color: var(--quality-risk);
  }

  .venue-head span {
    overflow-wrap: anywhere;
    color: var(--subtle);
    font-size: 10px;
    text-align: right;
  }

  .contract,
  .source-error,
  .caveat {
    margin: var(--space-xs) 0 0;
  }

  dl {
    display: grid;
    gap: 1px;
    margin: var(--space-sm) 0 0;
    background: var(--line);
  }

  dl div {
    min-width: 0;
    padding: var(--space-xs) var(--space-sm);
    background: var(--panel);
  }

  dt {
    color: var(--muted);
    font-size: 9px;
  }

  dd {
    margin: 2px 0 0;
    overflow-wrap: anywhere;
    color: var(--text);
    font-size: 10px;
    font-variant-numeric: tabular-nums;
  }

  dl small,
  time {
    display: block;
    margin-top: 2px;
    overflow-wrap: anywhere;
  }

  .caveat {
    margin: 0;
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--line);
  }

  @media (max-width: 48rem) {
    .venues {
      grid-template-columns: 1fr;
    }
  }
</style>
