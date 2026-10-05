<script lang="ts">
  import { preferences } from "$lib/theme/workspace-preferences";
  import type { RankedRow } from "$lib/generated/ranking-response";
  import { formatPriceChange } from "$lib/market/price-change";
  import { DEFAULT_TURNOVER_DECIMALS } from "$lib/market/turnover-format";
  import { relativeVolumeDescription, relativeVolumeState, turnoverBarHeights } from "$lib/market/relative-volume";

  let { row, expired = false, isNew = false, showAsset = false, decimals = DEFAULT_TURNOVER_DECIMALS, onselect }: {
    row: RankedRow; expired?: boolean; isNew?: boolean; showAsset?: boolean; decimals?: number; onselect: () => void;
  } = $props();
  const signal = $derived(relativeVolumeState(row, expired, $preferences));
  const bars = $derived(turnoverBarHeights(row.turnoverComparison));
  const fresh = $derived(isNew && signal.kind !== null);
  const description = $derived(`${fresh ? "新着 · " : ""}${relativeVolumeDescription(row, expired, decimals, $preferences, $preferences.percentDecimals, $preferences.ratioDecimals)}`);
</script>

<button type="button" class="volume-signal" class:with-asset={showAsset} class:surge={signal.kind !== null}
  class:fresh class:up={signal.direction === "up"} class:down={signal.direction === "down"}
  title={description} aria-label={`${description}\n選択して詳細を確認`}
  data-testid="relative-volume-signal" data-state={signal.kind ?? (signal.available ? "normal" : "unavailable")}
  data-new={fresh} onclick={onselect}>
  {#if showAsset}<strong>{row.asset}</strong>{/if}
  <span class="marks" aria-hidden="true">
    <svg class="direction" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      {#if expired}
        <circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" />
      {:else if signal.direction === "up"}
        <path d="m3 17 6-6 4 3 8-10M15 4h6v6" />
      {:else if signal.direction === "down"}
        <path d="m3 7 6 6 4-3 8 10M15 20h6v-6" />
      {:else if signal.direction === "flat"}
        <path d="M5 12h14" />
      {:else}
        <path d="M9 8a3 3 0 1 1 5 2c-1 1-2 1-2 4M12 18h.01" />
      {/if}
    </svg>
    <svg class="volume-bars" viewBox="0 0 36 28">
      {#if signal.available && bars}
        {#each bars as height, index}
          <rect x={2 + index * 12} y={25 - height} width="7" {height} rx="1"
            class:current={index === 2} class:history={index !== 2} />
          {#if height === 0}<path d={`M${2 + index * 12} 25h7`} class="zero" />{/if}
        {/each}
      {:else}
        <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <circle cx="18" cy="14" r="9" /><path d="M15 11a3 3 0 1 1 5 2c-1 1-2 1-2 3M18 20h.01" />
        </g>
      {/if}
    </svg>
    {#if fresh}<span class="new-dot"></span>{/if}
  </span>
  {#if showAsset}<span class="change">{row.returnPct === null ? "—" : formatPriceChange(row.returnPct, $preferences.percentDecimals)}</span>{/if}
</button>

<style>
  .volume-signal { position: relative; display: inline-flex; align-items: center; justify-content: center; padding: 2px 4px; min-height: 34px; min-width: 68px; border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--muted); vertical-align: middle; }
  .volume-signal:hover { background: var(--panel-strong); border-color: var(--line-strong); }
  .marks { position: relative; display: inline-flex; align-items: center; gap: 7px; flex-shrink: 0; }
  .direction { width: 20px; height: 20px; }
  .up .direction, .up .change { color: var(--up); }
  .down .direction, .down .change { color: var(--down); }
  .volume-bars { width: 36px; height: 28px; color: var(--muted); }
  .history { fill: var(--muted); opacity: .7; }
  .current { fill: var(--text); }
  .surge .current { fill: var(--activity); }
  .zero { stroke: var(--muted); stroke-width: 1; }
  .new-dot { position: absolute; width: 5px; height: 5px; top: -2px; right: -4px; border-radius: 50%; background: var(--activity); }
  .fresh .marks { animation: volume-arrival 650ms ease-out; }
  .with-asset { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: var(--space-xs); width: 100%; padding: var(--space-sm); border-color: var(--line); text-align: left; background: var(--panel-solid); }
  .with-asset strong { color: var(--text); font-size: var(--type-data-md-size); min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .with-asset .marks { grid-column: 2; grid-row: 1 / span 2; }
  .with-asset .change { grid-column: 1; font-size: var(--type-body-sm-size); font-variant-numeric: tabular-nums; }
  @keyframes volume-arrival { from { transform: scale(.9); } to { transform: scale(1); } }
  @media (max-width: 960px) {
    .volume-signal { min-height: 44px; }
    .with-asset { padding-block: var(--space-xs); }
  }
  @media (prefers-reduced-motion: reduce) { .fresh .marks { animation: none; } }
</style>
