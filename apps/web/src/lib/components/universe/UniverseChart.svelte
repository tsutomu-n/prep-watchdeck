<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
  import type {
    MarketChartArtifact,
    Timeframe
  } from "$lib/generated/market-chart";
  import {
    applyChartFontFamily,
    applyChartThemePalette,
    readChartFontFamily,
    readChartThemePalette
  } from "$lib/market/chart-theme";
  import { COLOR_SCHEME_CHANGE_EVENT } from "$lib/theme/color-scheme";
  import { FONT_SCHEME_CHANGE_EVENT } from "$lib/theme/font-scheme";

  type ChartModule = typeof import("lightweight-charts");

  let {
    payload,
    venueInstrumentId
  }: {
    payload: MarketChartArtifact;
    venueInstrumentId: string;
  } = $props();

  const timeframes: Timeframe[] = ["5m", "15m", "1h", "4h", "24h"];
  let timeframe = $state<Timeframe>("15m");
  let container = $state<HTMLDivElement | null>(null);
  let chartApi: IChartApi | null = null;
  let candles: ISeriesApi<"Candlestick"> | null = null;
  let volumes: ISeriesApi<"Histogram"> | null = null;
  let observer: ResizeObserver | null = null;
  let loadError = $state<string | null>(null);
  let activeFrame = $derived(payload.timeframes.find((item) => item.timeframe === timeframe));
  let bars = $derived(activeFrame?.bars ?? []);
  let incompleteCount = $derived(bars.filter((bar) => !bar.complete).length);
  let summary = $derived(
    bars.length === 0
      ? `${venueInstrumentId} ${timeframe} ローソク足データなし`
      : `${venueInstrumentId} ${timeframe} ${bars.length}本、未完全部分 ${incompleteCount}本`
  );
  let chartQualityLabel = $derived(
    {
      ready: "正常",
      partial: "一部取得",
      unavailable: "取得不能",
      stale: "期限切れ"
    }[payload.status]
  );

  onMount(async () => {
    const target = container;
    if (!target) return;
    try {
      const module = await import("lightweight-charts");
      if (!container || container !== target) return;
      createChart(module, target);
      updateSeries();
      observer = new ResizeObserver(() => chartApi?.timeScale().fitContent());
      observer.observe(target);
      window.addEventListener(COLOR_SCHEME_CHANGE_EVENT, updateTheme);
      window.addEventListener(FONT_SCHEME_CHANGE_EVENT, updateFont);
    } catch (cause) {
      loadError = cause instanceof Error ? cause.message : "チャートを表示できません";
    }
  });

  onDestroy(() => {
    if (typeof window !== "undefined") {
      window.removeEventListener(COLOR_SCHEME_CHANGE_EVENT, updateTheme);
      window.removeEventListener(FONT_SCHEME_CHANGE_EVENT, updateFont);
    }
    observer?.disconnect();
    chartApi?.remove();
    chartApi = null;
    candles = null;
    volumes = null;
  });

  $effect(() => {
    payload.generatedAt;
    timeframe;
    bars;
    updateSeries();
  });

  function createChart(module: ChartModule, target: HTMLDivElement) {
    const palette = readChartThemePalette(getComputedStyle(target));
    const { CandlestickSeries, ColorType, HistogramSeries, createChart } = module;
    chartApi = createChart(target, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: palette.surface },
        textColor: palette.text,
        fontFamily: readChartFontFamily(getComputedStyle(target))
      },
      grid: {
        vertLines: { color: palette.grid },
        horzLines: { color: palette.grid }
      },
      rightPriceScale: {
        borderColor: palette.border,
        scaleMargins: { top: 0.05, bottom: 0.3 }
      },
      timeScale: { borderColor: palette.border, timeVisible: true, secondsVisible: false }
    });
    candles = chartApi.addSeries(CandlestickSeries, {
      upColor: palette.up,
      downColor: palette.down,
      borderUpColor: palette.up,
      borderDownColor: palette.down,
      wickUpColor: palette.up,
      wickDownColor: palette.down,
      priceLineVisible: false
    });
    volumes = chartApi.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false
    });
    chartApi.priceScale("volume").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  }

  function updateSeries() {
    if (!chartApi || !candles || !volumes) return;
    const palette = container ? readChartThemePalette(getComputedStyle(container)) : null;
    candles.setData(
      bars.map((bar) => ({
        time: toTimestamp(bar.bucketAt),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close
      }))
    );
    volumes.setData(
      bars.map((bar) => ({
        time: toTimestamp(bar.bucketAt),
        value: bar.volumeNotional ?? bar.volumeBase ?? 0,
        color: palette ? (bar.close >= bar.open ? palette.volumeUp : palette.volumeDown) : undefined
      }))
    );
    chartApi.timeScale().fitContent();
  }

  function updateTheme() {
    if (!container || !chartApi || !candles) return;
    try {
      applyChartThemePalette(
        { chart: chartApi, candlestick: candles, line: emptyLineTarget },
        readChartThemePalette(getComputedStyle(container))
      );
      updateSeries();
    } catch (cause) {
      loadError = cause instanceof Error ? cause.message : "配色を適用できません";
    }
  }

  function updateFont() {
    if (!container || !chartApi) return;
    applyChartFontFamily(chartApi, readChartFontFamily(getComputedStyle(container)));
  }

  function toTimestamp(value: string) {
    return Math.floor(Date.parse(value) / 1000) as UTCTimestamp;
  }

  const emptyLineTarget = { applyOptions: () => undefined };
</script>

<section class="chart-panel" aria-labelledby="market-chart-title" aria-describedby="market-chart-summary">
  <div class="chart-heading">
    <div>
      <h3 id="market-chart-title">価格・出来高</h3>
      <p>{venueInstrumentId} / Venue配信ローソク足</p>
    </div>
    <div class="timeframes" aria-label="チャート時間軸">
      {#each timeframes as option}
        <button
          type="button"
          class:active={timeframe === option}
          aria-pressed={timeframe === option}
          onclick={() => (timeframe = option)}
        >{option}</button>
      {/each}
    </div>
  </div>
  <p id="market-chart-summary" class="sr-only" aria-live="polite">{summary}</p>
  {#if loadError}
    <p class="chart-message" role="alert">{loadError}</p>
  {:else}
    <div class="chart-wrap">
      <div bind:this={container} class="chart-surface" aria-hidden="true"></div>
      {#if bars.length === 0}
        <p class="chart-message">ローソク足データなし</p>
      {/if}
    </div>
  {/if}
  {#if incompleteCount > 0}
    <p class="quality-note">不完全な集約bar {incompleteCount}本を含みます。判断時は品質理由を確認してください。</p>
  {/if}
  {#if payload.status !== "ready" || payload.qualityReasons.length > 0}
    <p class="quality-note">
      Chart品質: {chartQualityLabel} / {payload.qualityReasons.join(" / ") || "理由なし"}
    </p>
  {/if}
</section>

<style>
  .chart-panel {
    border-top: 1px solid var(--line);
    background: var(--chart-surface);
  }

  .chart-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-sm);
    min-height: 54px;
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--chart-grid);
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    color: var(--chart-text);
    font-size: var(--type-heading-md-size);
  }

  .chart-heading p,
  .quality-note {
    margin-top: var(--space-xxs);
    color: var(--chart-text);
    font-size: var(--type-body-sm-size);
  }

  .timeframes {
    display: flex;
    gap: var(--space-xs);
  }

  button {
    min-width: 38px;
    min-height: var(--control-height-dense);
    border: 1px solid var(--chart-border);
    border-radius: var(--radius-none);
    background: var(--chart-surface);
    color: var(--chart-text);
    font: inherit;
    cursor: pointer;
  }

  button.active {
    border-color: var(--chart-focus);
    background: var(--chart-focus);
    color: var(--focus-on);
  }

  .chart-wrap {
    position: relative;
  }

  .chart-surface {
    width: 100%;
    height: 340px;
  }

  .chart-message {
    display: grid;
    place-items: center;
    min-height: 220px;
    padding: var(--space-md);
    color: var(--chart-text);
  }

  .chart-wrap .chart-message {
    position: absolute;
    inset: 0;
    min-height: 0;
  }

  .quality-note {
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--chart-grid);
    color: var(--warning);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }

  @media (max-width: 48rem) {
    .chart-heading {
      align-items: stretch;
      flex-direction: column;
    }

    .timeframes {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }

    button {
      min-height: var(--control-height-touch);
    }

    .chart-surface {
      height: 280px;
    }
  }
</style>
