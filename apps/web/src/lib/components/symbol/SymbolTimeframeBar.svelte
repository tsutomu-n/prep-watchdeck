<script lang="ts">
  let {
    symbol,
    selectedTimeframe,
    timeframes
  }: {
    symbol: string;
    selectedTimeframe: string;
    timeframes: readonly string[];
  } = $props();
</script>

<nav class="timeframe-bar" aria-label="時間軸">
  {#each timeframes as timeframe}
    <a
      class:active={selectedTimeframe === timeframe}
      aria-current={selectedTimeframe === timeframe ? "page" : undefined}
      data-single-line-action
      href={`/symbols/${encodeURIComponent(symbol)}?tf=${timeframe}`}
    >
      {timeframe}
    </a>
  {/each}
</nav>

<style>
  .timeframe-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 8px;
    border-bottom: 1px solid var(--line);
  }

  .timeframe-bar a {
    display: grid;
    place-items: center;
    box-sizing: border-box;
    min-width: 46px;
    padding: 8px 10px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: color-mix(in srgb, var(--panel-strong) 90%, transparent);
    color: inherit;
    text-align: center;
    text-decoration: none;
    font-weight: 800;
    white-space: nowrap;
  }

  .timeframe-bar a.active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  .timeframe-bar a:focus-visible {
    outline: 2px solid var(--focus);
    outline-offset: 2px;
  }

  .timeframe-bar a:active {
    background: var(--panel-strong);
  }

  .timeframe-bar a.active:active {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .timeframe-bar a {
      min-width: 44px;
      min-height: 44px;
      padding-block: 0;
    }
  }

  @media (max-width: 360px) {
    .timeframe-bar {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--space-sm);
    }

    .timeframe-bar a {
      width: 100%;
      padding-inline: 0;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .timeframe-bar a:hover {
      border-color: var(--focus);
    }
  }
</style>
