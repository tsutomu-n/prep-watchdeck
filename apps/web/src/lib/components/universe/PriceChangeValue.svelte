<script lang="ts">
  import {
    PRICE_CHANGE_MAX_AGE_MS,
    dailyBaselineAt,
    formatPriceChange,
    priceChangeUnavailableLabel
  } from "$lib/market/price-change";
  import type { PriceChangeState } from "$lib/market/price-change-client";
  import { formatFinite, formatTimestamp } from "$lib/market/universe-view";

  let { state, referenceTime, versionId, now, supported = true, detailed = false } = $props<{
    state?: PriceChangeState;
    referenceTime: string;
    versionId: number;
    now: number;
    supported?: boolean;
    detailed?: boolean;
  }>();

  let result = $derived(state?.data ?? null);
  let compatible = $derived(Boolean(result && result.referenceTime === referenceTime
    && result.venueInstrumentVersionId === versionId
    && Date.parse(result.baselineAt) === dailyBaselineAt(now, referenceTime)
    && now - Date.parse(result.generatedAt) <= PRICE_CHANGE_MAX_AGE_MS));
  let change = $derived(state?.status === "ready" && compatible ? result?.changePercent ?? null : null);
  let reason = $derived.by(() => {
    if (change !== null) return null;
    if (!supported) return "group未確定";
    if (state?.status === "unavailable" && compatible && result?.reason) {
      return priceChangeUnavailableLabel(result.reason);
    }
    if (result && !compatible) return "更新待ち";
    if (state?.status === "error") return state.message ?? "取得できません";
    if (state?.status === "stale") return "更新待ち";
    if (state?.status === "loading") return "取得中";
    if (state?.status === "queued") return "待機中";
    return state?.message ?? "表示時に取得";
  });
  let title = $derived(result && change !== null
    ? `約定価格: ${formatFinite(result.currentPrice)} / 基準価格: ${formatFinite(result.baselinePrice)} / 基準: ${formatTimestamp(result.baselineAt)} JST / 取得: ${formatTimestamp(result.generatedAt)} JST`
    : `JST ${referenceTime}基準の約定騰落率: ${reason}`);
</script>

<span class="price-change" class:detailed {title}>
  {#if change !== null}
    <strong class:up={change >= 0.005} class:down={change <= -0.005}>{formatPriceChange(change)}</strong>
  {:else}
    <span class="missing">— <small>{reason}</small></span>
  {/if}
</span>
{#if detailed && result && change !== null}
  <dl>
    <div><dt>約定価格</dt><dd>{formatFinite(result.currentPrice)}</dd></div>
    <div><dt>基準価格</dt><dd>{formatFinite(result.baselinePrice)}</dd></div>
    <div><dt>基準日時 · JST</dt><dd>{formatTimestamp(result.baselineAt)}</dd></div>
    <div><dt>取得時刻 · JST</dt><dd>{formatTimestamp(result.generatedAt)}</dd></div>
  </dl>
{/if}

<style>
  .price-change { font-variant-numeric: tabular-nums; }
  strong { font-size: var(--type-data-md-size); font-weight: var(--type-data-md-weight); white-space: nowrap; }
  .up { color: var(--up); }
  .down { color: var(--down); }
  .missing { color: var(--muted); }
  small { display: block; font-size: var(--type-label-caps-size); }
  .detailed strong { font-size: var(--type-data-lg-size); }
  .detailed .missing { display: block; }
  .detailed small { display: inline; }
  dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: var(--space-sm) 0 0; }
  dl > div { min-width: 0; padding: var(--space-sm); border-top: 1px solid var(--line); }
  dt { color: var(--muted); font-size: var(--type-label-caps-size); }
  dd { margin: var(--space-xxs) 0 0; font-size: var(--type-body-sm-size); overflow-wrap: anywhere; }
</style>
