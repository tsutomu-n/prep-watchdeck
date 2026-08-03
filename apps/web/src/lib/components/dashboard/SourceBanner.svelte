<script lang="ts">
  import { dataSourceLabel, snapshotStatusLabel, templateLabel } from "$lib/market/labels";

  let {
    dataSource,
    status,
    fixtureSet,
    templateName
  }: {
    dataSource: string;
    status: string;
    fixtureSet?: string | null;
    templateName?: string | null;
  } = $props();
</script>

<div class="source-banner" data-status={status}>
  <span>{dataSourceLabel(dataSource)}</span>
  <strong role="status" aria-live="polite" aria-atomic="true">
    {snapshotStatusLabel(status)}
  </strong>
  <small>{templateLabel(fixtureSet ?? templateName)}</small>
</div>

<style>
  .source-banner {
    display: grid;
    gap: 4px;
    min-width: 150px;
    padding: 7px 10px;
    border: 1px solid var(--line-strong);
    background: var(--surface);
    color: var(--text);
    box-shadow: none;
    text-transform: uppercase;
  }

  .source-banner strong {
    color: var(--quality-good);
  }

  .source-banner[data-status="STALE"],
  .source-banner[data-status="PARTIAL"] {
    border-color: var(--warning-border);
  }

  .source-banner[data-status="STALE"] strong,
  .source-banner[data-status="PARTIAL"] strong {
    color: var(--warning);
  }

  .source-banner[data-status="ERROR"] {
    border-color: var(--quality-risk);
  }

  .source-banner[data-status="ERROR"] strong {
    color: var(--quality-risk);
  }

  .source-banner span,
  .source-banner small {
    font-size: 11px;
  }

  @media (max-width: 960px) {
    .source-banner {
      width: 100%;
      min-width: 0;
      box-sizing: border-box;
    }
  }

  @media (max-width: 560px) {
    .source-banner {
      padding: var(--space-xs);
    }
  }
</style>
