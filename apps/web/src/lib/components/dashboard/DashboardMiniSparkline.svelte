<script lang="ts">
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { miniSparklineData } from "$lib/market/mini-sparkline";

  let {
    row,
    selectedTimeframe
  }: {
    row: ScannerRowDTO;
    selectedTimeframe: string;
  } = $props();

  let sparkline = $derived(miniSparklineData(row, selectedTimeframe));
</script>

<span class={`mini-spark ${sparkline.direction}`} aria-hidden="true">
  {#if sparkline.path}
    <svg viewBox="0 0 72 22" preserveAspectRatio="none" focusable="false">
      <path d={sparkline.path} />
    </svg>
  {/if}
  {#if sparkline.volumeBars.length > 0}
    <span class="mini-volume">
      {#each sparkline.volumeBars as bar}
        <span class={bar.className} style={`height: ${bar.height}px`}></span>
      {/each}
    </span>
  {/if}
</span>

<style>
  .mini-spark {
    display: grid;
    grid-area: spark;
    align-content: center;
    gap: 3px;
    width: 72px;
    height: 40px;
  }

  .mini-spark svg {
    display: block;
    width: 72px;
    height: 22px;
    overflow: visible;
  }

  .mini-spark path {
    fill: none;
    stroke: var(--subtle);
    stroke-linecap: round;
    stroke-linejoin: round;
    stroke-width: 2;
    vector-effect: non-scaling-stroke;
  }

  .mini-spark.up path {
    stroke: var(--up);
  }

  .mini-spark.down path {
    stroke: var(--down);
  }

  .mini-volume {
    display: grid;
    grid-template-columns: repeat(16, 1fr);
    align-items: end;
    gap: 1px;
    width: 72px;
    height: 12px;
  }

  .volume-bar {
    display: block;
    min-height: 2px;
    border-radius: 1px 1px 0 0;
    background: var(--chip-line);
    opacity: 0.68;
  }

  .volume-bar.up {
    background: color-mix(in srgb, var(--up) 68%, var(--surface));
  }

  .volume-bar.down {
    background: color-mix(in srgb, var(--down) 68%, var(--surface));
  }

  .volume-bar.strong {
    opacity: 1;
  }

  .volume-bar.strong.up {
    background: var(--up);
  }

  .volume-bar.strong.down {
    background: var(--down);
  }
</style>
