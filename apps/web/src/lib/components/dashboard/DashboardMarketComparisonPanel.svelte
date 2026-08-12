<script lang="ts">
  import { formatDateTime, formatMarketPrice, formatNumber } from "$lib/market/format";
  import {
    marketComparisonSourceLabel,
    type MarketComparisonSummary
  } from "$lib/market/market-comparison";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";

  let { summary }: { summary: MarketComparisonSummary } = $props();

  let readyCount = $derived(summary.symbols.filter((item) => item.status === "ready").length);
</script>

<section class="market-comparison" aria-label="3市場価格比較">
  <header class="panel-header">
    <div>
      <h3>3市場価格比較</h3>
      <small>Mark price / 5分更新</small>
      <p>Bitget・Hyperliquid・Bybitの表示専用比較です。</p>
    </div>
    <strong>{readyCount} / {summary.symbols.length} 銘柄</strong>
  </header>

  <div class="symbols">
    {#each summary.symbols as item (item.symbol)}
      <article aria-label={`${formatDisplaySymbol(item.symbol)} 3市場価格`}>
        <header class="symbol-header">
          <h4 title={item.symbol}>{formatDisplaySymbol(item.symbol)}</h4>
          <span class:incomplete={item.status !== "ready"}>
            {item.coverage.valid} / {item.coverage.required}
          </span>
        </header>

        <dl>
          <div>
            <dt>参考中央値</dt>
            <dd>{formatMarketPrice(item.medianMarkPrice)}</dd>
          </div>
          <div>
            <dt>最大乖離幅</dt>
            <dd>{item.spreadPct === null ? "-" : formatNumber(item.spreadPct, "%")}</dd>
          </div>
        </dl>

        <ul aria-label={`${formatDisplaySymbol(item.symbol)} 市場別Mark price`}>
          {#each item.sources as source}
            <li class:unavailable={source.status !== "ok"}>
              <span>{marketComparisonSourceLabel(source.source)}</span>
              <strong>{formatMarketPrice(source.markPrice)}</strong>
              <small>{source.quote ?? "未取得"}</small>
              <time
                datetime={source.observedAt === null
                  ? undefined
                  : new Date(source.observedAt).toISOString()}
              >
                {source.observedAt === null
                  ? source.error ?? "取得失敗"
                  : formatDateTime(source.observedAt)}
              </time>
            </li>
          {/each}
        </ul>
      </article>
    {/each}
  </div>

  <p class="caveat">
    USDT建ての参考値です。HyperliquidはUSDC証拠金で、通貨換算はしていません。ランキングや売買判定には使いません。
  </p>
</section>

<style>
  .market-comparison {
    border: 1px solid var(--line-strong);
    border-top: 0;
    background: var(--panel);
  }

  .panel-header,
  .symbol-header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-md);
  }

  .panel-header {
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  h3,
  h4,
  p,
  ul {
    margin: 0;
  }

  h3 {
    font-size: var(--type-heading-md-size);
  }

  h4,
  .symbol-header span {
    font-size: 12px;
  }

  .panel-header small,
  .panel-header p,
  .panel-header > strong,
  .caveat {
    color: var(--subtle);
    font-size: 10px;
    line-height: 1.4;
  }

  .panel-header small {
    display: block;
    margin-top: 2px;
    color: var(--muted);
  }

  .panel-header p {
    margin-top: var(--space-xs);
  }

  .panel-header > strong {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  .symbols {
    display: grid;
    gap: 1px;
    background: var(--line);
  }

  article {
    min-width: 0;
    background: var(--panel);
  }

  .symbol-header {
    padding: var(--space-xs) var(--space-md);
    background: var(--panel-strong);
  }

  .symbol-header span {
    color: var(--chip-neutral);
  }

  .symbol-header span.incomplete,
  li.unavailable strong,
  li.unavailable time {
    color: var(--warning);
  }

  dl {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1px;
    margin: 1px 0 0;
    background: var(--line);
  }

  dl div {
    min-width: 0;
    padding: var(--space-xs) var(--space-md);
    background: var(--panel-strong);
  }

  dt,
  li small,
  li time {
    color: var(--muted);
    font-size: 9px;
  }

  dd {
    margin: 2px 0 0;
    color: var(--text);
    font-size: 11px;
    overflow-wrap: anywhere;
  }

  ul {
    padding: 0;
    list-style: none;
  }

  li {
    display: grid;
    grid-template-columns: minmax(70px, 1fr) minmax(76px, auto) 36px;
    align-items: baseline;
    gap: var(--space-xs);
    padding: var(--space-xs) var(--space-md);
    border-top: 1px solid var(--line);
  }

  li span,
  li strong {
    font-size: 10px;
  }

  li strong {
    text-align: right;
  }

  li time {
    grid-column: 1 / -1;
    overflow-wrap: anywhere;
  }

  .caveat {
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--line);
  }
</style>
