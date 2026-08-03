<script lang="ts">
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import {
    vpiDataQualityLabel,
    vpiStateLabel,
    type VpiLitePlusItem,
    type VpiLitePlusSummary
  } from "$lib/market/vpi-lite-plus";

  let { summary }: { summary: VpiLitePlusSummary } = $props();

  let items = $derived([
    ...summary.benchmarks.map((item) => ({ item, kind: "Benchmark" as const })),
    ...summary.targets.map((item) => ({ item, kind: "Target" as const }))
  ]);

  function stateTone(item: VpiLitePlusItem): "neutral" | "warn" | "risk" {
    if (item.dataQuality === "STALE" || item.dataQuality === "ERROR") return "risk";
    if (
      item.dataQuality === "INSUFFICIENT" ||
      item.state === "THIN_VOLATILITY" ||
      item.state === "SINGLE_BAR_SUSPECT"
    ) {
      return "warn";
    }
    return "neutral";
  }
</script>

{#if items.length > 0}
  <section class="vpi-panel" aria-label="VPI-Lite+ 実験表示">
    <header>
      <div>
        <h3>VPI-Lite+ 実験表示</h3>
        <p>実験中の補助指標です。売買シグナルではありません。</p>
      </div>
      <span>Cold snapshot</span>
    </header>
    <ul>
      {#each items as { item, kind } (item.symbol)}
        <li>
          <div>
            <strong title={item.symbol}>{formatDisplaySymbol(item.symbol)}</strong>
            <span>{kind}</span>
          </div>
          <div class="state-line">
            <b class={stateTone(item)}>{vpiStateLabel(item.state)}</b>
            {#if item.dataQuality !== "OK" && vpiDataQualityLabel(item.dataQuality) !== vpiStateLabel(item.state)}
              <small>{vpiDataQualityLabel(item.dataQuality)}</small>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  .vpi-panel {
    border-block: 1px solid var(--line-strong);
    background: var(--panel-strong);
  }

  header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-md);
    padding: var(--space-md);
    border-bottom: 1px solid var(--line);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: var(--type-heading-md-size);
    line-height: var(--type-heading-md-leading);
  }

  p,
  header > span {
    color: var(--subtle);
    font-size: 11px;
    line-height: 1.35;
  }

  p {
    margin-top: var(--space-xs);
  }

  header > span {
    flex: 0 0 auto;
    white-space: nowrap;
  }

  ul {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1px;
    margin: 0;
    padding: 0;
    background: var(--line);
    list-style: none;
  }

  li {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-sm);
    min-width: 0;
    min-height: 42px;
    padding: var(--space-sm) var(--space-md);
    box-sizing: border-box;
    background: var(--panel);
  }

  li > div:first-child,
  .state-line {
    min-width: 0;
  }

  strong,
  li span,
  b,
  small {
    display: block;
  }

  strong {
    overflow-wrap: anywhere;
    font-size: 12px;
  }

  li span,
  small {
    margin-top: 2px;
    color: var(--muted);
    font-size: 10px;
  }

  .state-line {
    text-align: right;
  }

  b {
    color: var(--chip-neutral);
    font-size: 11px;
    line-height: 1.25;
  }

  b.warn {
    color: var(--warning);
  }

  b.risk {
    color: var(--quality-risk);
  }

  @media (max-width: 560px) {
    header {
      display: grid;
    }

    ul {
      grid-template-columns: 1fr;
    }
  }
</style>
