<script lang="ts">
  import type { SnapshotSourceDTO } from "$lib/generated/scanner-snapshot";
  import type { ServiceStateView } from "$lib/service-state";
  import ServiceStatusBadge from "./ServiceStatusBadge.svelte";
  import SourceBanner from "./SourceBanner.svelte";

  let {
    source,
    status,
    runtime = null,
    serviceState,
    refreshSecondsRemaining = null,
    refreshProgressPct = 0,
    isAutoReloading = false
  }: {
    source: SnapshotSourceDTO;
    status: string;
    runtime?: {
      target: "local" | "cloudflare";
      localCommandsEnabled: boolean;
      localCommandsAvailable: boolean;
      cloudflareReady: false;
      labels: string[];
    } | null;
    serviceState?: { view?: ServiceStateView } | null;
    refreshSecondsRemaining?: number | null;
    refreshProgressPct?: number;
    isAutoReloading?: boolean;
  } = $props();
</script>

<header class="topbar">
  <div>
    <p class="kicker">準備監視板</p>
    <h1>ローカル市場監視</h1>
  </div>
  <div class="status-stack">
    <SourceBanner
      dataSource={source.dataSource}
      {status}
      fixtureSet={source.fixtureSet}
      templateName={source.templateName}
    />
    <ServiceStatusBadge
      {serviceState}
      {refreshSecondsRemaining}
      {refreshProgressPct}
      {isAutoReloading}
    />
    {#if runtime}
      <div class="runtime-stack" aria-label="runtime boundary">
        {#each runtime.labels as label}
          <span class:enabled={label === "LOCAL COMMANDS ENABLED"} class:disabled={label === "LOCAL COMMANDS DISABLED"}>
            {label}
          </span>
        {/each}
      </div>
    {/if}
  </div>
</header>

<style>
  .topbar {
    display: flex;
    align-items: end;
    justify-content: space-between;
    gap: 16px;
    box-sizing: border-box;
    width: 100%;
    max-width: 1440px;
    margin: 0 auto 16px;
  }

  .kicker,
  h1 {
    margin: 0;
  }

  .kicker {
    color: var(--muted);
    font-size: 11px;
    letter-spacing: 0;
    text-transform: uppercase;
  }

  h1 {
    margin-top: 2px;
    font-size: clamp(22px, 2.4vw, 32px);
    line-height: 0.95;
    letter-spacing: 0;
  }

  .status-stack {
    display: flex;
    align-items: stretch;
    gap: 10px;
  }

  .runtime-stack {
    display: grid;
    align-content: stretch;
    gap: 3px;
    min-width: 176px;
    border: 1px solid color-mix(in srgb, var(--muted) 28%, transparent);
    background: color-mix(in srgb, var(--bg-alt) 72%, transparent);
    padding: 6px;
  }

  .runtime-stack span {
    display: block;
    color: var(--subtle);
    font-size: 10px;
    line-height: 1.2;
    overflow-wrap: anywhere;
  }

  .runtime-stack span.enabled {
    color: var(--quality-good);
  }

  .runtime-stack span.disabled {
    color: var(--warning);
  }

  @media (max-width: 960px) {
    .topbar {
      display: grid;
      grid-template-columns: 1fr;
      box-sizing: border-box;
      width: 100%;
    }

    .status-stack {
      display: grid;
      grid-template-columns: 1fr;
    }

    .runtime-stack {
      min-width: 0;
    }
  }

  @media (max-width: 560px) {
    .status-stack {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: var(--space-xs);
    }

    .runtime-stack {
      padding: var(--space-xs);
    }
  }
</style>
