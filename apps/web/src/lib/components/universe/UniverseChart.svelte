<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { IChartApi, ISeriesApi, LogicalRange, TickMarkType, Time, UTCTimestamp } from "lightweight-charts";
  import {
    CHART_TIMEFRAMES,
    type ChartCandle,
    type ChartHistory,
    type Timeframe
  } from "$lib/market/chart-history";
  import { chartVolumeValue } from "$lib/market/market-state-presentation";
  import {
    chartRangeAfterUpdate,
    formatChartTick,
    formatChartTime,
    mergeChartBars
  } from "$lib/market/chart-view";
  import {
    applyChartFontFamily,
    applyChartThemePalette,
    readChartFontFamily,
    readChartThemePalette
  } from "$lib/market/chart-theme";
  import { COLOR_SCHEME_CHANGE_EVENT } from "$lib/theme/color-scheme";
  import { FONT_SCHEME_CHANGE_EVENT } from "$lib/theme/font-scheme";

  type ChartModule = typeof import("lightweight-charts");
  type HistoryContext = {
    instrument: string;
    timeframe: Timeframe;
    controller: AbortController;
    loadingLatest: boolean;
    loadingHistory: boolean;
    initialized: boolean;
    viewportSet: boolean;
  };

  let {
    venueInstrumentId,
    timeframe = $bindable<Timeframe>("15m")
  }: {
    venueInstrumentId: string;
    timeframe?: Timeframe;
  } = $props();

  const historyPollMs = 60_000;
  const maxLoadedBars = 10_000;
  let container = $state<HTMLDivElement | null>(null);
  let chartApi: IChartApi | null = null;
  let candles: ISeriesApi<"Candlestick"> | null = null;
  let volumes: ISeriesApi<"Histogram"> | null = null;
  let context: HistoryContext | null = null;
  let renderedContext: HistoryContext | null = null;
  let renderedBars: ChartCandle[] = [];
  let applyingData = false;
  let chartReady = $state(false);
  let bars = $state<ChartCandle[]>([]);
  let loading = $state(true);
  let loadingHistory = $state(false);
  let hasMore = $state(false);
  let nextBefore = $state<string | null>(null);
  let loadError = $state<string | null>(null);
  let historyError = $state<string | null>(null);
  let renderError = $state<string | null>(null);
  let visiblePeriod = $state("—");
  let selectionKey = $derived(`${venueInstrumentId}/${timeframe}`);
  let incompleteCount = $derived(bars.filter((bar) => !bar.complete).length);
  let summary = $derived(
    `${venueInstrumentId} ${timeframe === "24h" ? "1D" : timeframe} ${bars.length}本、未確定 ${incompleteCount}本`
  );

  onMount(() => {
    let mounted = true;
    const target = container;
    if (target) {
      void import("lightweight-charts").then((module) => {
        if (!mounted) return;
        createChart(module, target);
        chartReady = true;
        window.addEventListener(COLOR_SCHEME_CHANGE_EVENT, updateTheme);
        window.addEventListener(FONT_SCHEME_CHANGE_EVENT, updateFont);
      }).catch(() => {
        if (mounted) renderError = "チャートを表示できません";
      });
    }
    return () => {
      mounted = false;
      window.removeEventListener(COLOR_SCHEME_CHANGE_EVENT, updateTheme);
      window.removeEventListener(FONT_SCHEME_CHANGE_EVENT, updateFont);
      chartApi?.remove();
      chartApi = null;
      candles = null;
      volumes = null;
    };
  });

  $effect.pre(() => {
    selectionKey;
    return untrack(() => {
      const current: HistoryContext = {
        instrument: venueInstrumentId,
        timeframe,
        controller: new AbortController(),
        loadingLatest: false,
        loadingHistory: false,
        initialized: false,
        viewportSet: false
      };
      context = current;
      bars = [];
      hasMore = false;
      nextBefore = null;
      loading = true;
      loadingHistory = false;
      loadError = null;
      historyError = null;
      visiblePeriod = "—";
      void loadLatest(current);
      const timer = window.setInterval(() => {
        if (document.visibilityState !== "hidden") void loadLatest(current);
      }, historyPollMs);
      return () => {
        current.controller.abort();
        window.clearInterval(timer);
        if (context === current) context = null;
      };
    });
  });

  $effect(() => {
    chartReady;
    bars;
    untrack(updateSeries);
  });

  async function requestPage(current: HistoryContext, before?: string): Promise<ChartHistory> {
    const query = new URLSearchParams({
      instrument: current.instrument,
      timeframe: current.timeframe
    });
    if (before) query.set("before", before);
    const response = await fetch(`/api/chart-history?${query}`, {
      cache: "no-store",
      signal: current.controller.signal
    });
    if (!response.ok) throw new Error("chart history unavailable");
    const result = await response.json() as ChartHistory;
    if (result.venueInstrumentId !== current.instrument || result.timeframe !== current.timeframe) {
      throw new Error("chart history identity mismatch");
    }
    return result;
  }

  function isCurrent(current: HistoryContext) {
    return context === current && !current.controller.signal.aborted;
  }

  async function loadLatest(current: HistoryContext) {
    if (current.loadingLatest || !isCurrent(current)) return;
    current.loadingLatest = true;
    try {
      const result = await requestPage(current);
      if (!isCurrent(current)) return;
      const first = result.bars[0]?.bucketAt;
      // A fresh page replaces its entire time window, including corrections/deletions.
      const older = first ? bars.filter((bar) => bar.bucketAt < first) : [];
      bars = mergeChartBars(older, result.bars).slice(-maxLoadedBars);
      if (!current.initialized || older.length === 0) {
        hasMore = result.hasMore;
        nextBefore = result.nextBefore;
      }
      current.initialized = true;
      loadError = null;
    } catch {
      if (isCurrent(current)) {
        loadError = bars.length > 0
          ? "チャートの更新が止まっています。最後に取得できた価格を表示しています。"
          : "ローソク足を取得できません。再試行してください。";
      }
    } finally {
      current.loadingLatest = false;
      if (isCurrent(current)) loading = false;
    }
  }

  async function loadOlder() {
    const current = context;
    if (!current || !isCurrent(current) || current.loadingHistory || current.loadingLatest ||
        !hasMore || !nextBefore || bars.length >= maxLoadedBars) return;
    current.loadingHistory = true;
    loadingHistory = true;
    const before = nextBefore;
    try {
      const result = await requestPage(current, before);
      if (!isCurrent(current)) return;
      const remaining = maxLoadedBars - bars.length;
      bars = mergeChartBars(bars, result.bars.slice(-remaining));
      hasMore = result.hasMore && result.nextBefore !== before;
      nextBefore = result.nextBefore;
      historyError = null;
    } catch {
      if (isCurrent(current)) historyError = "過去のローソク足を取得できませんでした。再試行できます。";
    } finally {
      current.loadingHistory = false;
      if (isCurrent(current)) loadingHistory = false;
    }
  }

  function createChart(module: ChartModule, target: HTMLDivElement) {
    const palette = readChartThemePalette(getComputedStyle(target));
    const { CandlestickSeries, ColorType, HistogramSeries, TickMarkType, createChart } = module;
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
      localization: { locale: "ja-JP", timeFormatter: formatChartTime },
      timeScale: {
        borderColor: palette.border,
        timeVisible: true,
        secondsVisible: false,
        lockVisibleTimeRangeOnResize: true,
        shiftVisibleRangeOnNewBar: false,
        tickMarkFormatter: (time: Time, type: TickMarkType) => formatChartTick(time,
          type === TickMarkType.Year ? "year" :
          type === TickMarkType.Month ? "month" :
          type === TickMarkType.DayOfMonth ? "day" : "time")
      }
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
    chartApi.timeScale().subscribeVisibleTimeRangeChange((range) => {
      visiblePeriod = range ? `${formatChartTime(range.from)} — ${formatChartTime(range.to)}` : "—";
    });
    chartApi.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (!applyingData && context?.viewportSet && range && range.from < 20 && !historyError) {
        void loadOlder();
      }
    });
  }

  function updateSeries() {
    if (!chartApi || !candles || !volumes) return;
    const sameContext = renderedContext === context;
    const previous = sameContext ? renderedBars : [];
    const visible = sameContext ? chartApi.timeScale().getVisibleLogicalRange() : null;
    const range = chartRangeAfterUpdate(previous, bars, visible);
    const palette = container ? readChartThemePalette(getComputedStyle(container)) : null;
    applyingData = true;
    try {
      chartApi.applyOptions({ timeScale: { timeVisible: timeframe !== "24h" } });
      candles.setData(bars.map((bar) => ({
        time: toTimestamp(bar.bucketAt), open: bar.open, high: bar.high, low: bar.low, close: bar.close
      })));
      volumes.setData(bars.flatMap((bar) => {
        const value = chartVolumeValue(bar.volumeNotional, bar.volumeBase);
        return value === null ? [] : [{
          time: toTimestamp(bar.bucketAt),
          value,
          color: palette ? (bar.close >= bar.open ? palette.volumeUp : palette.volumeDown) : undefined
        }];
      }));
      if (range) chartApi.timeScale().setVisibleLogicalRange(range as LogicalRange);
      renderedBars = bars;
      renderedContext = context;
      if (context && bars.length > 0) context.viewportSet = true;
      renderError = null;
    } catch {
      renderError = "チャートを表示できません";
    } finally {
      applyingData = false;
    }
  }

  function updateTheme() {
    if (!container || !chartApi || !candles) return;
    try {
      applyChartThemePalette(
        { chart: chartApi, candlestick: candles, line: emptyLineTarget },
        readChartThemePalette(getComputedStyle(container))
      );
      updateSeries();
    } catch {
      renderError = "配色を適用できません";
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
      <p>{venueInstrumentId} / 取引所のローソク足</p>
    </div>
    <div class="timeframe-controls">
      <span>時間足</span>
      <div class="timeframes" aria-label="チャート時間足">
        {#each CHART_TIMEFRAMES as option}
          <button
            type="button"
            class:active={timeframe === option}
            aria-pressed={timeframe === option}
            title={option === "24h" ? "1日足（1本が1日）" : `${option}足`}
            onclick={() => (timeframe = option)}
          >{option === "24h" ? "1D" : option}</button>
        {/each}
      </div>
    </div>
  </div>
  <p id="market-chart-summary" class="sr-only" aria-live="polite">{summary}</p>
  <div class="chart-wrap" aria-busy={loading}>
    <div bind:this={container} class="chart-surface" aria-hidden="true"></div>
    {#if renderError}
      <p class="chart-message" role="alert">{renderError}</p>
    {:else if bars.length === 0}
      <p class="chart-message">{loading ? "ローソク足を読み込み中" : loadError ? "ローソク足を表示できません" : "ローソク足データなし"}</p>
    {/if}
  </div>
  <div class="chart-footer">
    <output aria-label="チャート表示期間">表示期間: {visiblePeriod}</output>
    <div class="chart-actions">
      <button type="button" disabled={bars.length === 0} onclick={() => chartApi?.timeScale().scrollToRealTime()}>最新へ</button>
      <button type="button" disabled={bars.length === 0} onclick={() => chartApi?.timeScale().fitContent()}>全体表示</button>
      {#if hasMore && bars.length < maxLoadedBars}
        <button type="button" disabled={loading || loadingHistory} onclick={() => void loadOlder()}>
          {loadingHistory ? "読み込み中" : "さらに過去を読み込む"}
        </button>
      {/if}
    </div>
    <p>時刻 JST · {bars.length}本 · 過去へスクロールして履歴を追加</p>
    {#if timeframe === "24h"}<p>日足の区切り 09:00 JST</p>{/if}
    {#if bars.length >= maxLoadedBars}<p>表示上限10,000本です。時間足を大きくすると長い期間を確認できます。</p>{/if}
    {#if incompleteCount > 0}<p>未確定の足 {incompleteCount}本を含みます。</p>{/if}
  </div>
  {#if loadError}
    <div class="quality-note" role="alert">
      <p>{loadError}</p>
      <button type="button" onclick={() => context && void loadLatest(context)}>再試行</button>
    </div>
  {/if}
  {#if historyError}<p class="quality-note" role="alert">{historyError}</p>{/if}
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
  .timeframe-controls {
    display: grid;
    gap: var(--space-xs);
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
  button:disabled {
    cursor: default;
    opacity: 0.5;
  }
  .chart-footer {
    display: grid;
    gap: var(--space-xs);
    padding: var(--space-sm) var(--space-md);
    border-top: 1px solid var(--chart-grid);
    color: var(--chart-text);
    font-size: var(--type-body-sm-size);
  }
  .chart-footer output {
    overflow-wrap: anywhere;
    font-variant-numeric: tabular-nums;
  }
  .chart-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
  }
  .chart-actions button,
  .quality-note button {
    padding-inline: var(--space-sm);
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
    display: grid;
    gap: var(--space-xxs);
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
  @media (max-width: 22.5rem) {
    .timeframes {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }
</style>
