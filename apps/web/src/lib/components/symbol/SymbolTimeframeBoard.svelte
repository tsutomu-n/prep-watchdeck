<script lang="ts">
  import { formatCompactNumber as fmtCompact } from "$lib/market/format";
  import { changeTone } from "$lib/market/labels";

  type TimeframeRow = {
    timeframe: string;
    change: number | null | undefined;
    turnover: number | null | undefined;
    volumeRatio: number | null | undefined;
  };

  let {
    symbol,
    selectedTimeframe,
    rows
  }: {
    symbol: string;
    selectedTimeframe: string;
    rows: TimeframeRow[];
  } = $props();

  function volumeRatioText(value: number | null | undefined) {
    return typeof value === "number" && Number.isFinite(value) ? `${fmtCompact(value)}×` : "—";
  }
</script>

<section id="symbol-timeframes" class="timeframe-board" aria-label="時間軸別データ" tabindex="-1">
  <div class="board-head">
    <h2>時間軸別の変化と売買代金</h2>
  </div>
  <div class="tf-grid">
    {#each rows as item}
      <a
        class:active={selectedTimeframe === item.timeframe}
        aria-current={selectedTimeframe === item.timeframe ? "page" : undefined}
        href={`/symbols/${encodeURIComponent(symbol)}?tf=${item.timeframe}`}
      >
        <span>{item.timeframe}</span>
        <strong class={changeTone(item.change)}>{fmtCompact(item.change, "%")}</strong>
        <small>{fmtCompact(item.turnover)} USDT</small>
        {#if item.timeframe === "15m"}
          <em>15分量倍率 {volumeRatioText(item.volumeRatio)}</em>
        {/if}
      </a>
    {/each}
  </div>
</section>

<style>
  .timeframe-board {
    max-width: 1440px;
    margin: 8px auto 0;
    border: 1px solid var(--line);
    background: var(--panel);
  }

  .board-head {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 12px;
    border-bottom: 1px solid var(--line);
  }

  .board-head h2 {
    margin: 0;
    font-size: 15px;
  }

  .tf-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 0;
    background: transparent;
  }

  .tf-grid a {
    display: grid;
    gap: 3px;
    min-width: 0;
    padding: 10px;
    border: 0;
    border-right: 1px solid var(--line);
    background: transparent;
    color: inherit;
    text-decoration: none;
  }

  .tf-grid a:last-child {
    border-right: 0;
  }

  .tf-grid a:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: -2px;
  }

  .tf-grid a:active {
    background: var(--panel-strong);
  }

  .tf-grid a.active {
    background: var(--focus);
    color: var(--focus-on);
  }

  .tf-grid span {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
  }

  .tf-grid strong {
    font-size: 22px;
  }

  .tf-grid small,
  .tf-grid em {
    overflow: hidden;
    color: var(--muted);
    font-size: 11px;
    font-style: normal;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .good {
    color: var(--up);
  }

  .risk {
    color: var(--down);
  }

  .tf-grid a.active strong,
  .tf-grid a.active small,
  .tf-grid a.active em,
  .tf-grid a.active span {
    color: var(--focus-on);
  }

  @media (max-width: 720px) {
    .tf-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .tf-grid a {
      border-right: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }

    .tf-grid a:nth-child(even) {
      border-right: 0;
    }

    .tf-grid a:nth-last-child(-n + 2) {
      border-bottom: 0;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .tf-grid a {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .tf-grid a:hover {
      border-color: var(--focus);
    }
  }
</style>
