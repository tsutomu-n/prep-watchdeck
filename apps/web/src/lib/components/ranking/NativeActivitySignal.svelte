<script lang="ts">
  import type { ActivityValue, ActivityWindow, NativeActivityRow } from "$lib/generated/native-activity";
  import { displayNumber } from "$lib/market/number-display";
  import { formatPriceChange } from "$lib/market/price-change";
  import { rankingTimestamp } from "$lib/market/ranking";
  import { DEFAULT_TURNOVER_DECIMALS, formatTurnover } from "$lib/market/turnover-format";
  import { preferences } from "$lib/theme/workspace-preferences";

  let { row, reason, decimals = DEFAULT_TURNOVER_DECIMALS, onselect }: {
    row: NativeActivityRow | null; reason: string | null; decimals?: number; onselect: () => void;
  } = $props();

  const windows = $derived([row?.windows["15m"], row?.windows["1h"]]);
  const price = $derived(ready(windows[0]?.current.priceChangePct));
  const ratios = $derived(windows.map((window) => ready(window?.relativeRatio)));
  const previous = $derived(windows.map((window) => ready(window?.previousChangePct)));
  const values = $derived(Array.from({ length: 4 }, (_, index) => ready(windows[0]?.history[index]?.turnover)));
  const maximum = $derived(Math.max(0, ...values.filter((value): value is number => value !== null)));
  const description = $derived([
    `Bitget ${row?.sourceSymbol ?? "短期アクティビティ"} · 売買代金 USDT`,
    ...(row ? windows.map((window, index) => describe(window, index === 0 ? "15分" : "1時間"))
      : [reason ?? "短期データなし"]),
    "棒は直近4つの15分区間（古→新）。欠測は中段の破線、実測ゼロは下端の線。矢印は15分の価格方向。",
    `普段比${displayNumber($preferences.surgeRatio, $preferences.ratioDecimals)}倍以上を強調。選択して詳細を確認。`
  ].join("\n"));

  function ready(value: ActivityValue | undefined): number | null {
    return value?.status === "ready" && typeof value.value === "number" && Number.isFinite(value.value) ? value.value : null;
  }

  function unavailable(value: ActivityValue | undefined): string {
    return value ? {
      ready: "値なし", history_missing: "履歴不足", invalid_data: "入力不整合",
      no_baseline: "比較基準なし", low_baseline: "比較基準が少額"
    }[value.status] : "短期データなし";
  }

  function describe(window: ActivityWindow | undefined, label: string): string {
    if (!window) return `${label}: 短期データなし`;
    const turnover = ready(window.current.turnover);
    const ratio = ready(window.relativeRatio);
    const previous = ready(window.previousChangePct);
    const change = ready(window.current.priceChangePct);
    return `${label} ${rankingTimestamp(Date.parse(window.current.startAt))} → ${rankingTimestamp(Date.parse(window.current.endAt))} JST` +
      ` · 売買代金 ${turnover === null ? unavailable(window.current.turnover) : `${formatTurnover(turnover, decimals)} USDT`}` +
      ` · 普段比 ${ratio === null ? unavailable(window.relativeRatio) : `${displayNumber(ratio, $preferences.ratioDecimals)}倍`}` +
      `（過去7日の同時刻区間中央値、${window.baselineDays}/7日）` +
      ` · 前区間比 ${previous === null ? unavailable(window.previousChangePct) : formatPriceChange(previous, $preferences.percentDecimals)}` +
      ` · 価格 ${change === null ? unavailable(window.current.priceChangePct) : formatPriceChange(change, $preferences.percentDecimals)}`;
  }
</script>

<button type="button" class="native-activity-signal" title={description} aria-label={description}
  data-testid="native-activity-signal" data-state={row ? "available" : "unavailable"} onclick={onselect}>
  <span class="window-label" aria-hidden="true">15m</span>
  <strong class:surge={ratios[0] !== null && ratios[0] >= $preferences.surgeRatio}
    class:missing={ratios[0] === null} aria-hidden="true">{ratios[0] === null ? "—" : `${displayNumber(ratios[0], $preferences.ratioDecimals)}×`}</strong>
  <span class="previous" class:missing={previous[0] === null} aria-hidden="true">前{previous[0] === null ? "—" : `${displayNumber(previous[0], $preferences.percentDecimals, false, true)}%`}</span>
  <span class="window-label" aria-hidden="true">1h</span>
  <strong class:surge={ratios[1] !== null && ratios[1] >= $preferences.surgeRatio}
    class:missing={ratios[1] === null} aria-hidden="true">{ratios[1] === null ? "—" : `${displayNumber(ratios[1], $preferences.ratioDecimals)}×`}</strong>
  <span class="previous" class:missing={previous[1] === null} aria-hidden="true">前{previous[1] === null ? "—" : `${displayNumber(previous[1], $preferences.percentDecimals, false, true)}%`}</span>
  <span class="price-and-history" aria-hidden="true">
    <span class="window-label">価</span>
    <svg class="price-direction" class:up={price !== null && price > 0} class:down={price !== null && price < 0}
    viewBox="0 0 24 14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
    data-testid="native-activity-price-direction" data-direction={price === null ? "unavailable" : price > 0 ? "up" : price < 0 ? "down" : "flat"}>
    {#if price === null}<path d="M9 7h6" stroke-dasharray="1 3" />
    {:else if price > 0}<path d="M5 11 18 3M11 3h7v7" />
    {:else if price < 0}<path d="m5 3 13 8M11 11h7V4" />
    {:else}<path d="M5 7h13m-4-4 4 4-4 4" />{/if}
    </svg>
    <span class="price-value" class:up={price !== null && price > 0} class:down={price !== null && price < 0} class:missing={price === null}>{price === null ? "—" : `${displayNumber(price, $preferences.percentDecimals)}%`}</span>
  <svg class="activity-bars" viewBox="0 0 28 14" aria-hidden="true" data-testid="native-activity-bars">
    {#each values as value, index}
      {@const height = value === null || maximum === 0 ? 0 : Math.max(1, value / maximum * 12)}
      <g data-status={value === null ? "missing" : "ready"}>
        {#if value === null}<path class="gap" d={`M${index * 7 + 1} 7h4`} />
        {:else if value === 0}<path class="zero" d={`M${index * 7 + 1} 13h4`} />
        {:else}<rect x={index * 7 + 1} y={13 - height} width="4" {height}
          class:current={index === 3} class:surge={index === 3 && ratios[0] !== null && ratios[0] >= $preferences.surgeRatio} />{/if}
      </g>
    {/each}
    </svg>
  </span>
</button>

<style>
  .native-activity-signal { box-sizing: border-box; display: inline-grid; grid-template-columns: max-content minmax(20px, 1fr) minmax(0, max-content); align-items: center; gap: 0 3px; width: 120px; max-width: 100%; min-height: var(--control-height-dense); padding: 1px 2px; border: 1px solid transparent; border-radius: var(--radius-xs); background: transparent; color: var(--text); font: inherit; font-size: var(--type-label-caps-size); line-height: 1.15; text-align: right; vertical-align: middle; font-variant-numeric: tabular-nums; }
  .native-activity-signal:hover { background: var(--panel-strong); border-color: var(--line-strong); }
  .native-activity-signal:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
  .window-label { color: var(--muted); text-align: left; }
  strong, .previous, .price-value { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  strong { font-weight: 650; }.previous { color: var(--subtle); }
  .price-and-history { grid-column: 1 / -1; display: grid; grid-template-columns: max-content 14px minmax(0, 1fr) 24px; align-items: center; gap: 1px; }
  .surge { color: var(--activity); }.missing { color: var(--muted); }
  .price-direction, .activity-bars { display: block; width: 24px; height: 14px; color: var(--muted); }.price-direction { width: 14px; }
  .up { color: var(--up); }.down { color: var(--down); }
  rect { fill: var(--muted); }rect.current { fill: var(--text); }rect.surge { fill: var(--activity); }
  .gap, .zero { stroke: var(--muted); stroke-width: 1; }.gap { stroke-dasharray: 1 1; }
  @media (max-width: 960px), (pointer: coarse) {
    .native-activity-signal { min-height: var(--control-height-touch); }
  }
</style>
