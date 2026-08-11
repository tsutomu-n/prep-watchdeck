<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import type { IChartApi, ISeriesApi } from "lightweight-charts";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import {
    buildChartAccessibleSummary,
    buildChartData,
    buildChartDataFromPayload,
    buildLineData,
    buildVolumeData,
    type ChartCandle
  } from "$lib/market/chart-data";
  import {
    applyChartFontFamily,
    applyChartThemePalette,
    readChartFontFamily,
    readChartThemePalette,
    type ChartThemePalette
  } from "$lib/market/chart-theme";
  import { formatDisplaySymbol } from "$lib/market/symbol-display";
  import { COLOR_SCHEME_CHANGE_EVENT } from "$lib/theme/color-scheme";
  import { FONT_SCHEME_CHANGE_EVENT } from "$lib/theme/font-scheme";

  type ChartModule = typeof import("lightweight-charts");

  const componentId = $props.id();

  let {
    row,
    timeframe,
    runId,
    size = "compact"
  }: {
    row: ScannerRowDTO | null;
    timeframe: string;
    runId: string;
    size?: "compact" | "analysis";
  } = $props();

  let container = $state<HTMLDivElement | null>(null);
  let chart = $state<IChartApi | null>(null);
  let candleSeries = $state<ISeriesApi<"Candlestick"> | null>(null);
  let volumeSeries = $state<ISeriesApi<"Histogram"> | null>(null);
  let lineSeries = $state<ISeriesApi<"Line"> | null>(null);
  let resizeObserver: ResizeObserver | null = null;
  let colorSchemeChangeListener: (() => void) | null = null;
  let fontSchemeChangeListener: (() => void) | null = null;
  let chartInstrumentationReported = false;
  let destroyed = false;
  let loadError = $state<string | null>(null);
  let remoteCandleData = $state<ChartCandle[]>([]);
  let chartPalette = $state<ChartThemePalette | null>(null);
  let candleData = $derived(remoteCandleData.length > 0 ? remoteCandleData : buildChartData(row, timeframe));
  let volumeData = $derived(
    chartPalette
      ? buildVolumeData(candleData, { up: chartPalette.volumeUp, down: chartPalette.volumeDown })
      : []
  );
  let lineData = $derived(buildLineData(row, timeframe));
  let displaySymbol = $derived(row ? formatDisplaySymbol(row.symbol) : "");
  let hasChartData = $derived(candleData.length > 0 || lineData.length > 0);
  let chartSummary = $derived(
    loadError ?? buildChartAccessibleSummary(displaySymbol, timeframe, candleData, lineData)
  );
  const chartSummaryId = `${componentId}-chart-summary`;

  onMount(async () => {
    const mountedContainer = container;
    if (!mountedContainer) return;

    let nextChart: IChartApi | null = null;
    try {
      let palette = readChartThemePalette(getComputedStyle(mountedContainer));
      let fontFamily = readChartFontFamily(getComputedStyle(mountedContainer));
      const chartModule = await loadChartModule();
      if (destroyed || container !== mountedContainer) return;

      palette = readChartThemePalette(getComputedStyle(mountedContainer));
      fontFamily = readChartFontFamily(getComputedStyle(mountedContainer));

      chartPalette = palette;
      const { CandlestickSeries, ColorType, HistogramSeries, LineSeries, createChart } = chartModule;
      nextChart = createChart(mountedContainer, {
        autoSize: true,
        layout: {
          background: { type: ColorType.Solid, color: palette.surface },
          textColor: palette.text,
          fontFamily
        },
        grid: {
          vertLines: { color: palette.grid },
          horzLines: { color: palette.grid }
        },
        rightPriceScale: {
          borderColor: palette.border,
          scaleMargins: {
            top: 0.05,
            bottom: 0.32
          }
        },
        timeScale: {
          borderColor: palette.border,
          timeVisible: true,
          secondsVisible: false
        },
        crosshair: {
          mode: 0
        }
      });
      const nextSeries = nextChart.addSeries(CandlestickSeries, {
        upColor: palette.up,
        downColor: palette.down,
        borderUpColor: palette.up,
        borderDownColor: palette.down,
        wickUpColor: palette.up,
        wickDownColor: palette.down,
        priceLineVisible: false
      });
      const nextVolumeSeries = nextChart.addSeries(HistogramSeries, {
        priceFormat: {
          type: "volume"
        },
        priceScaleId: "volume",
        priceLineVisible: false
      });
      const nextLineSeries = nextChart.addSeries(LineSeries, {
        color: palette.focus,
        lineWidth: 2,
        priceLineVisible: false
      });
      nextChart.priceScale("volume").applyOptions({
        scaleMargins: {
          top: 0.76,
          bottom: 0
        }
      });

      chart = nextChart;
      candleSeries = nextSeries;
      volumeSeries = nextVolumeSeries;
      lineSeries = nextLineSeries;
      updateSeries();

      resizeObserver = new ResizeObserver(() => {
        chart?.timeScale().fitContent();
      });
      resizeObserver.observe(mountedContainer);
      chartInstrumentation()?.chartResizeObserverCreated?.();
      chartInstrumentation()?.chartCreated?.();
      chartInstrumentationReported = true;

      colorSchemeChangeListener = () => {
        if (!container || !chart || !candleSeries || !lineSeries) return;
        try {
          const nextPalette = readChartThemePalette(getComputedStyle(container));
          applyChartThemePalette(
            { chart, candlestick: candleSeries, line: lineSeries },
            nextPalette
          );
          chartPalette = nextPalette;
        } catch (error) {
          loadError =
            error instanceof Error && /^(Missing|Invalid) chart theme token:/.test(error.message)
              ? `チャートを表示できません: ${error.message}`
              : "チャートを表示できません";
        }
      };
      window.addEventListener(COLOR_SCHEME_CHANGE_EVENT, colorSchemeChangeListener);
      fontSchemeChangeListener = () => {
        if (!container || !chart) return;
        try {
          applyChartFontFamily(chart, readChartFontFamily(getComputedStyle(container)));
        } catch (error) {
          loadError = chartStyleError(error);
        }
      };
      window.addEventListener(FONT_SCHEME_CHANGE_EVENT, fontSchemeChangeListener);
    } catch (error) {
      cleanupChart(nextChart);
      if (!destroyed) {
        loadError = chartStyleError(error);
      }
    }
  });

  onDestroy(() => {
    destroyed = true;
    if (colorSchemeChangeListener) {
      window.removeEventListener(COLOR_SCHEME_CHANGE_EVENT, colorSchemeChangeListener);
      colorSchemeChangeListener = null;
    }
    if (fontSchemeChangeListener) {
      window.removeEventListener(FONT_SCHEME_CHANGE_EVENT, fontSchemeChangeListener);
      fontSchemeChangeListener = null;
    }
    cleanupChart();
  });

  $effect(() => {
    row?.symbol;
    timeframe;
    runId;
    const symbol = row?.symbol;
    const selectedTimeframe = timeframe;
    const snapshotRunId = runId;
    remoteCandleData = [];
    if (!symbol || !snapshotRunId) return;

    const controller = new AbortController();
    const query = new URLSearchParams({ tf: selectedTimeframe, runId: snapshotRunId });
    fetch(`/api/symbols/${encodeURIComponent(symbol)}/chart?${query.toString()}`, {
      signal: controller.signal
    })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => {
        if (controller.signal.aborted || !payload) return;
        remoteCandleData = buildChartDataFromPayload(payload, selectedTimeframe);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          remoteCandleData = [];
        }
      });

    return () => controller.abort();
  });

  $effect(() => {
    row?.symbol;
    timeframe;
    candleData;
    volumeData;
    lineData;
    updateSeries();
  });

  function updateSeries() {
    if (!candleSeries || !volumeSeries || !lineSeries || !chart) return;
    if (candleData.length > 0) {
      candleSeries.setData(candleData);
      volumeSeries.setData(volumeData);
      lineSeries.setData([]);
    } else {
      candleSeries.setData([]);
      volumeSeries.setData([]);
      lineSeries.setData(lineData);
    }
    chart.timeScale().fitContent();
  }

  function cleanupChart(fallbackChart: IChartApi | null = null) {
    const observerToDisconnect = resizeObserver;
    const chartToRemove = chart ?? fallbackChart;
    const shouldReportRemoval = chartInstrumentationReported;
    resizeObserver = null;
    chart = null;
    candleSeries = null;
    volumeSeries = null;
    lineSeries = null;
    chartInstrumentationReported = false;

    if (observerToDisconnect) {
      observerToDisconnect.disconnect();
      chartInstrumentation()?.chartResizeObserverDisconnected?.();
    }
    if (chartToRemove) {
      chartToRemove.remove();
      if (shouldReportRemoval) chartInstrumentation()?.chartRemoved?.();
    }
  }

  function chartInstrumentation() {
    return (
      window as Window & {
        __watchdeckInstrumentation?: {
          chartCreated?: () => void;
          chartRemoved?: () => void;
          chartResizeObserverCreated?: () => void;
          chartResizeObserverDisconnected?: () => void;
          loadChartModule?: (loadDefault: () => Promise<ChartModule>) => Promise<ChartModule>;
        };
      }
    ).__watchdeckInstrumentation;
  }

  function loadChartModule() {
    const loadDefault = () => import("lightweight-charts");
    return chartInstrumentation()?.loadChartModule?.(loadDefault) ?? loadDefault();
  }

  function chartStyleError(error: unknown) {
    return error instanceof Error &&
      (/^(Missing|Invalid) chart theme token:/.test(error.message) ||
        /^Missing chart font token:/.test(error.message))
      ? `チャートを表示できません: ${error.message}`
      : "チャートを表示できません";
  }

</script>

<section
  class={`chart-card ${size}`}
  aria-label={row ? `${displaySymbol} チャート` : "チャート"}
  aria-describedby={chartSummaryId}
>
  <div class="chart-head">
    <div>
      <h3>価格・出来高チャート</h3>
      <p>{row ? `${displaySymbol} ${timeframe} 足` : "銘柄未選択"}</p>
    </div>
    <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer" data-single-line-action>
      提供元
    </a>
  </div>

  <p id={chartSummaryId} class="sr-only" aria-live="polite">{chartSummary}</p>

  {#if loadError}
    <p class="chart-empty" role="alert">{loadError}</p>
  {:else}
    <div class="chart-viewport">
      <div bind:this={container} class="chart-surface" aria-hidden="true"></div>
      {#if !hasChartData}
        <p class="chart-empty">ローソク足データなし</p>
      {/if}
    </div>
  {/if}
</section>

<style>
  .chart-card {
    border-bottom: 1px solid var(--chart-border);
    background: var(--chart-surface);
  }

  .chart-card.analysis {
    border: 0;
    background: transparent;
  }

  .chart-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    min-height: 48px;
    padding: 0 12px;
    border-bottom: 1px solid var(--chart-grid);
  }

  .chart-head h3,
  .chart-head p,
  .chart-empty {
    margin: 0;
  }

  .chart-head h3 {
    color: var(--chart-text);
    font-size: 12px;
  }

  .chart-head p {
    margin-top: 3px;
    color: var(--chart-text);
    font-size: 13px;
    font-weight: 800;
  }

  .chart-head a {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--chart-focus);
    font-size: 12px;
    text-decoration: none;
    white-space: nowrap;
  }

  .chart-head a:focus-visible {
    outline: 2px solid var(--chart-focus);
    outline-offset: 2px;
  }

  .chart-head a:active {
    background: var(--panel-strong);
  }

  .chart-viewport {
    position: relative;
  }

  .chart-surface {
    width: 100%;
    height: 220px;
  }

  .chart-card.analysis .chart-surface {
    height: min(52vh, 460px);
    min-height: 340px;
  }

  .chart-card.analysis .chart-head {
    min-height: 54px;
  }

  .chart-empty {
    display: grid;
    place-items: center;
    min-height: 160px;
    color: var(--chart-text);
    font-size: 13px;
  }

  .chart-viewport > .chart-empty {
    position: absolute;
    inset: 0;
    min-height: 0;
    pointer-events: none;
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

  .chart-card.analysis .chart-empty {
    min-height: 340px;
  }

  @media (max-width: 720px) {
    .chart-card.analysis .chart-surface,
    .chart-card.analysis .chart-empty {
      height: 320px;
      min-height: 320px;
    }
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .chart-head a {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .chart-head a:hover {
      text-decoration: underline;
    }
  }
</style>
