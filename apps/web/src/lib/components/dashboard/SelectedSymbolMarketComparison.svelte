<script lang="ts">
  import { formatDateTime, formatMarketPrice, formatNumber } from "$lib/market/format";
  import {
    marketComparisonSourceLabel,
    type MarketComparisonItem
  } from "$lib/market/market-comparison";

  let { item, generatedAt }: { item: MarketComparisonItem; generatedAt: number } = $props();
</script>

<section class="market-comparison" aria-label="選択銘柄 3市場価格比較">
  <header>
    <div>
      <h3>3市場価格比較</h3>
      <p>Mark priceの参考比較</p>
    </div>
    <strong class:incomplete={item.status !== "ready"}>
      {item.coverage.valid} / {item.coverage.required} 市場
    </strong>
  </header>

  <dl class="summary">
    <div>
      <dt>参考中央値</dt>
      <dd>{formatMarketPrice(item.medianMarkPrice)}</dd>
    </div>
    <div>
      <dt>最大乖離幅</dt>
      <dd>{item.spreadPct === null ? "-" : formatNumber(item.spreadPct, "%")}</dd>
    </div>
    <div>
      <dt>取得時点</dt>
      <dd>{formatDateTime(generatedAt)}</dd>
    </div>
  </dl>

  <div class="sources" role="list" aria-label="市場別Mark price">
    {#each item.sources as source}
      <div class:unavailable={source.status !== "ok"} role="listitem">
        <span>{marketComparisonSourceLabel(source.source)}</span>
        <strong>{formatMarketPrice(source.markPrice)}</strong>
        <small>{source.quote ?? "未取得"}</small>
        <time datetime={source.observedAt === null ? undefined : new Date(source.observedAt).toISOString()}>
          {source.observedAt === null ? source.error ?? "取得失敗" : formatDateTime(source.observedAt)}
        </time>
      </div>
    {/each}
  </div>

  <p class="caveat">USD / USDT建てを横断する参考値です。ランキングや売買判定には使いません。</p>
</section>

<style>
  .market-comparison {
    padding: var(--space-md);
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel);
  }

  header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-md);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: 12px;
  }

  header p,
  .caveat {
    margin-top: 2px;
    color: var(--muted);
    font-size: 9px;
  }

  header strong {
    color: var(--chip-neutral);
    font-size: 12px;
  }

  header strong.incomplete {
    color: var(--warning);
  }

  .summary {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1px;
    margin: var(--space-sm) 0 0;
    background: var(--line);
  }

  .summary div {
    min-width: 0;
    padding: var(--space-sm);
    background: var(--panel-strong);
  }

  dt,
  small,
  time {
    color: var(--muted);
    font-size: 9px;
  }

  dd {
    margin: 3px 0 0;
    color: var(--text);
    font-size: 11px;
    overflow-wrap: anywhere;
  }

  .sources {
    display: grid;
    gap: 1px;
    margin-top: 1px;
    background: var(--line);
  }

  .sources > div {
    display: grid;
    grid-template-columns: minmax(82px, 1fr) minmax(90px, auto) 42px minmax(128px, auto);
    align-items: baseline;
    gap: var(--space-sm);
    padding: var(--space-sm);
    background: var(--panel-strong);
  }

  .sources span,
  .sources strong {
    font-size: 11px;
  }

  .sources strong {
    text-align: right;
  }

  .sources .unavailable strong,
  .sources .unavailable time {
    color: var(--warning);
  }

  .caveat {
    margin-top: var(--space-sm);
    line-height: 1.5;
  }

  @media (max-width: 640px) {
    .summary {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .sources > div {
      grid-template-columns: minmax(76px, 1fr) minmax(78px, auto) 38px;
    }

    .sources time {
      grid-column: 1 / -1;
    }
  }
</style>
