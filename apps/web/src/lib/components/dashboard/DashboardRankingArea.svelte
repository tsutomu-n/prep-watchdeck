<script lang="ts">
  import type { RankingMetaValue, RankingTree } from "$lib/market/rankings";
  import DashboardRankingPanel from "$lib/components/dashboard/DashboardRankingPanel.svelte";

  type RankingTimeframe = "5m" | "15m" | "1h" | "4h" | "24h" | "74h";
  type RankingMetric = readonly [label: string, metric: string];

  let {
    rankings,
    candidateRuleText,
    volumeRatioBaseline,
    volumeRatioHelp,
    selectedTimeframe,
    timeframes,
    metrics,
    onTimeframeSelect
  }: {
    rankings: RankingTree | undefined;
    candidateRuleText: string;
    volumeRatioBaseline: string;
    volumeRatioHelp: string;
    selectedTimeframe: RankingTimeframe;
    timeframes: readonly RankingTimeframe[];
    metrics: readonly RankingMetric[];
    onTimeframeSelect: (timeframe: RankingTimeframe) => void;
  } = $props();

  let activeMetric = $state("changeUp");

  function metricTimeframe(metric: string): RankingTimeframe {
    return metric === "volumeUp" ? "15m" : selectedTimeframe;
  }

  function ranking(metric: string) {
    return rankings?.timeframes?.[metricTimeframe(metric)]?.[metric] ?? [];
  }

  function rankingMeta(metric: string): Required<Pick<RankingMetaValue, "limit" | "totalEligible">> {
    const items = ranking(metric);
    const meta = rankings?.meta?.timeframes?.[metricTimeframe(metric)]?.[metric];
    return {
      limit: meta?.limit ?? items.length,
      totalEligible: meta?.totalEligible ?? items.length
    };
  }

  function tabId(metric: string) {
    return `candidate-tab-${metric}`;
  }

  function panelId(metric: string) {
    return `candidate-panel-${metric}`;
  }

  function metricTabClass(metric: string) {
    if (metric === "changeUp") return "metric-up";
    if (metric === "changeDown") return "metric-down";
    return "metric-neutral";
  }

  function activateTab(metric: string, target?: HTMLButtonElement) {
    activeMetric = metric;
    target?.focus();
  }

  function handleTabKeydown(event: KeyboardEvent, index: number) {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % metrics.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + metrics.length) % metrics.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = metrics.length - 1;
    if (nextIndex === null) return;

    event.preventDefault();
    const tablist = (event.currentTarget as HTMLButtonElement).closest('[role="tablist"]');
    const tabs = tablist?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
    activateTab(metrics[nextIndex][1], tabs?.[nextIndex]);
  }
</script>

<section class="ranking-area" aria-label={`${selectedTimeframe} ランキング`}>
  <div class="toolbar">
    <div>
      <h2>候補の動き</h2>
      <p class="candidate-rule">{candidateRuleText}</p>
      <p class="volume-baseline" title={volumeRatioHelp}>15分量倍率: {volumeRatioBaseline}</p>
    </div>
    <div class="timeframe-strip" role="group" aria-label="時間軸">
      {#each timeframes as timeframe}
        <button
          type="button"
          class:active={selectedTimeframe === timeframe}
          aria-pressed={selectedTimeframe === timeframe}
          data-single-line-action
          onclick={() => onTimeframeSelect(timeframe)}
        >
          {timeframe}
        </button>
      {/each}
    </div>
  </div>

  <div class="desktop-rankings" data-candidate-representation="desktop">
    {#each metrics as [label, metric]}
      <DashboardRankingPanel
        {label}
        {metric}
        timeframe={metricTimeframe(metric)}
        items={ranking(metric)}
        totalEligible={rankingMeta(metric).totalEligible}
        volumeRatioHelp={metric === "volumeUp" ? volumeRatioHelp : ""}
      />
    {/each}
  </div>

  <div class="mobile-rankings" data-candidate-representation="mobile">
    <div class="candidate-tabs" role="tablist" aria-label="候補ランキング種別">
      {#each metrics as [label, metric], index}
        <button
          class={metricTabClass(metric)}
          id={tabId(metric)}
          type="button"
          role="tab"
          aria-selected={activeMetric === metric}
          aria-controls={panelId(metric)}
          tabindex={activeMetric === metric ? 0 : -1}
          onclick={(event) => activateTab(metric, event.currentTarget)}
          onkeydown={(event) => handleTabKeydown(event, index)}
        >{label.replace("順", "")}</button>
      {/each}
    </div>
    {#each metrics as [label, metric]}
      <DashboardRankingPanel
        {label}
        {metric}
        timeframe={metricTimeframe(metric)}
        items={ranking(metric)}
        totalEligible={rankingMeta(metric).totalEligible}
        panelId={panelId(metric)}
        labelledBy={tabId(metric)}
        hidden={activeMetric !== metric}
        volumeRatioHelp={metric === "volumeUp" ? volumeRatioHelp : ""}
      />
    {/each}
  </div>
</section>

<style>
  .ranking-area {
    border: 1px solid color-mix(in srgb, var(--muted) 22%, transparent);
    background: color-mix(in srgb, var(--bg-alt) 72%, transparent);
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px;
    border-bottom: 1px solid var(--line);
    background: var(--panel-strong);
  }

  .toolbar h2 { margin: 0; font-size: 16px; }

  .candidate-rule,
  .volume-baseline {
    margin: 4px 0 0;
    color: var(--muted);
    font-size: 11px;
    line-height: 1.35;
  }

  .volume-baseline { color: var(--subtle); }

  .timeframe-strip { display: flex; flex-wrap: wrap; gap: 6px; }

  .timeframe-strip button,
  .candidate-tabs button {
    min-height: 30px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: color-mix(in srgb, var(--panel-selected) 90%, transparent);
    color: var(--text);
    cursor: pointer;
    font: inherit;
    padding: 0 10px;
    white-space: nowrap;
  }

  .timeframe-strip button.active,
  .candidate-tabs button[aria-selected="true"] {
    border-color: var(--focus);
    background: var(--focus);
    color: var(--focus-on);
    font-weight: 800;
  }

  .candidate-tabs button.metric-up {
    box-shadow: inset 0 3px 0 var(--up);
  }

  .candidate-tabs button.metric-down {
    box-shadow: inset 0 3px 0 var(--down);
  }

  .candidate-tabs button.metric-up:not([aria-selected="true"]) {
    color: var(--up);
  }

  .candidate-tabs button.metric-down:not([aria-selected="true"]) {
    color: var(--down);
  }

  button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
  button:active { background: var(--panel-strong); }

  .desktop-rankings {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .mobile-rankings { display: none; }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .timeframe-strip button,
    .candidate-tabs button {
      min-width: 44px;
      min-height: 44px;
      box-sizing: border-box;
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .timeframe-strip button:hover,
    .candidate-tabs button:hover { border-color: var(--focus); color: var(--focus); }
    .timeframe-strip button.active:hover,
    .candidate-tabs button[aria-selected="true"]:hover { color: var(--focus-on); }
  }

  @media (max-width: 560px) {
    .toolbar { align-items: stretch; flex-direction: column; }
    .desktop-rankings { display: none; }
    .mobile-rankings {
      display: block;
      max-block-size: min(48svh, 28rem);
      overflow-y: auto;
      overscroll-behavior-y: auto;
      touch-action: pan-y;
    }
    .candidate-tabs {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      position: sticky;
      z-index: 1;
      top: 0;
      border-bottom: 1px solid var(--line);
      background: var(--panel-strong);
    }
    .candidate-tabs button { min-width: 0; padding-inline: 4px; border-width: 0 1px 0 0; }
    .candidate-tabs button:last-child { border-right: 0; }
  }

  @media (max-width: 360px) {
    .timeframe-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-sm); }
    .timeframe-strip button { width: 100%; padding-inline: 0; }
    .candidate-tabs button { font-size: 10px; }
  }
</style>
