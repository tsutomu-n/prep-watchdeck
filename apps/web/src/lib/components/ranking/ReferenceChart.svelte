<script lang="ts">
  import { onMount } from "svelte";
  import { CHART_INTERVALS, widgetDocument, type ChartInterval } from "$lib/market/ranking";
  import { COLOR_SCHEME_CHANGE_EVENT, colorSchemes, readDocumentColorScheme } from "$lib/theme/color-scheme";

  let { symbol, interval = $bindable<ChartInterval>("15") } = $props<{
    symbol: string; interval?: ChartInterval;
  }>();
  let theme = $state<"dark" | "light">("dark");
  let mounted = $state(false);
  let reload = $state(0);
  const documentText = $derived(widgetDocument(symbol, interval, theme));

  onMount(() => {
    const update = () => {
      theme = colorSchemes.find((scheme) => scheme.id === readDocumentColorScheme(document.documentElement))?.mode ?? "dark";
    };
    update(); mounted = true;
    window.addEventListener(COLOR_SCHEME_CHANGE_EVENT, update);
    return () => window.removeEventListener(COLOR_SCHEME_CHANGE_EVENT, update);
  });
</script>

<div class="chart-toolbar">
  <label>チャートの足
    <select aria-label="ランキングチャートの時間足" bind:value={interval}>
      {#each CHART_INTERVALS as option}<option value={option.value}>{option.label}</option>{/each}
    </select>
  </label>
  <button type="button" onclick={() => reload += 1}>チャートを再読込み</button>
</div>
<div class="chart-frame" data-testid="ranking-chart" data-symbol={symbol} data-interval={interval}>
  {#if mounted}
    {#key reload}
      <iframe title={`TradingView ${symbol}`} srcdoc={documentText} referrerpolicy="no-referrer"
        sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"></iframe>
    {/key}
  {/if}
</div>
<p class="chart-caption">{symbol} · JST · TradingViewの配信データ。ランキングは比較時刻までの確定足を使い、チャートには進行中の足も含まれます。表示できない場合は再読込みしてください。</p>

<style>
  .chart-toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-sm); padding: var(--space-sm) 0; }
  label { display: flex; align-items: center; gap: var(--space-sm); color: var(--muted); font-size: var(--type-body-sm-size); }
  select, button { min-height: var(--control-height-dense); border: 1px solid var(--line-strong); border-radius: 0; background: var(--surface); color: var(--text); padding: 0 var(--space-sm); font: inherit; font-size: var(--type-body-sm-size); }
  button { cursor: pointer; }
  .chart-frame { height: 580px; min-width: 0; background: var(--chart-surface); }
  iframe { width: 100%; height: 100%; border: 0; }
  .chart-caption { color: var(--muted); font-size: var(--type-label-caps-size); line-height: 1.5; overflow-wrap: anywhere; padding: var(--space-sm) 0; }
  @media (max-width: 960px) { .chart-frame { height: 440px; } select, button { min-height: var(--control-height-touch); } }
</style>
