<script lang="ts">
  import { formatLag, serviceStateLabel, type ServiceStateView } from "$lib/service-state";

  let {
    serviceState,
    refreshSecondsRemaining = null,
    refreshProgressPct = 0,
    isAutoReloading = false
  }: {
    serviceState?: { view?: ServiceStateView } | null;
    refreshSecondsRemaining?: number | null;
    refreshProgressPct?: number;
    isAutoReloading?: boolean;
  } = $props();
  let view = $derived(serviceState?.view ?? null);
  let canShowRefresh = $derived(view && refreshSecondsRemaining !== null);
  let refreshLabel = $derived(
    isAutoReloading
      ? "画面更新中"
      : refreshSecondsRemaining === null
        ? ""
        : `次回確認まで ${refreshSecondsRemaining}秒`
  );
  let refreshBarWidth = $derived(`${Math.max(0, Math.min(100, refreshProgressPct))}%`);
</script>

<div class="service-badge" data-status={view?.status ?? "missing"}>
  <strong role="status" aria-live="polite" aria-atomic="true">
    {view ? view.label : serviceStateLabel("missing")}
  </strong>
  {#if view}
    <span>1m足 {formatLag(view.dataLagSeconds)}</span>
    <small>WS {view.streamShards} shards / {view.streamSymbols} symbols</small>
    <small>補完 {view.backfillText}</small>
    {#if canShowRefresh}
      <div class="refresh-meter" aria-label={refreshLabel}>
        <span>{refreshLabel}</span>
        <div class="meter-track">
          <i style={`width: ${refreshBarWidth}`}></i>
        </div>
      </div>
    {/if}
  {:else}
    <span>service-stateなし</span>
  {/if}
</div>

<style>
  .service-badge {
    display: grid;
    gap: 3px;
    min-width: 176px;
    padding: 7px 10px;
    border: 1px solid var(--line-strong);
    background: var(--surface);
    color: var(--text);
    box-shadow: none;
  }

  .service-badge strong {
    color: var(--muted);
  }

  .service-badge[data-status="ok"] {
    border-color: var(--quality-good);
  }

  .service-badge[data-status="ok"] strong {
    color: var(--quality-good);
  }

  .service-badge[data-status="backfilling"],
  .service-badge[data-status="stale"] {
    border-color: var(--warning-border);
  }

  .service-badge[data-status="backfilling"] strong,
  .service-badge[data-status="stale"] strong {
    color: var(--warning);
  }

  .service-badge[data-status="error"],
  .service-badge[data-status="unreadable"],
  .service-badge[data-status="missing"] {
    border-color: var(--quality-risk);
  }

  .service-badge[data-status="error"] strong,
  .service-badge[data-status="unreadable"] strong,
  .service-badge[data-status="missing"] strong {
    color: var(--quality-risk);
  }

  .service-badge strong,
  .service-badge span,
  .service-badge small {
    font-size: 11px;
    line-height: 1.25;
  }

  .refresh-meter {
    display: grid;
    gap: 4px;
    margin-top: 2px;
  }

  .refresh-meter span {
    color: var(--subtle);
    font-variant-numeric: tabular-nums;
  }

  .meter-track {
    overflow: hidden;
    width: 100%;
    height: 3px;
    background: color-mix(in srgb, var(--line) 78%, transparent);
  }

  .meter-track i {
    display: block;
    height: 100%;
    background: var(--muted);
    transition: width 180ms linear;
  }

  @media (max-width: 960px) {
    .service-badge {
      width: 100%;
      min-width: 0;
      box-sizing: border-box;
    }
  }

  @media (max-width: 560px) {
    .service-badge {
      padding: var(--space-xs);
    }
  }
</style>
