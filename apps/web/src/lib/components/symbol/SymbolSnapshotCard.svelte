<script lang="ts">
  import type { PrepWatchdeckScannerSnapshot } from "$lib/generated/scanner-snapshot";
  import { formatDateTime as fmtDate } from "$lib/market/format";
  import { dataSourceLabel, snapshotStatusLabel } from "$lib/market/labels";

  let { snapshot }: { snapshot: PrepWatchdeckScannerSnapshot } = $props();
</script>

<section class="intel-card source-card" data-symbol-workspace-section>
  <h2>スナップショット</h2>
  <dl class="fact-list">
    <div>
      <dt>source</dt>
      <dd>{dataSourceLabel(snapshot.source.dataSource)}</dd>
    </div>
    <div>
      <dt>status</dt>
      <dd>{snapshotStatusLabel(snapshot.snapshotStatus)}</dd>
    </div>
    <div>
      <dt>data as of</dt>
      <dd>{fmtDate(snapshot.dataAsOf)}</dd>
    </div>
    <div>
      <dt>generated</dt>
      <dd>{fmtDate(snapshot.generatedAt)}</dd>
    </div>
  </dl>
</section>

<style>
  h2,
  dl,
  dd {
    margin: 0;
  }

  .intel-card {
    min-width: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    padding: 12px;
  }

  .intel-card h2 {
    font-size: 15px;
  }

  .source-card {
    grid-column: span 2;
  }

  .fact-list {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 0;
    margin-top: 10px;
    background: transparent;
  }

  .fact-list div {
    min-width: 0;
    padding: 10px;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .fact-list div:nth-child(odd) {
    border-right: 1px solid var(--line);
  }

  .fact-list div:nth-child(n + 3) {
    border-top: 1px solid var(--line);
  }

  dt {
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
  }

  dd {
    margin-top: 5px;
    overflow-wrap: anywhere;
    font-size: 15px;
    font-weight: 850;
  }

  @media (max-width: 720px) {
    .source-card {
      grid-column: auto;
    }

    .fact-list {
      grid-template-columns: 1fr;
    }

    .fact-list div:nth-child(odd) {
      border-right: 0;
    }

    .fact-list div:nth-child(n + 2) {
      border-top: 1px solid var(--line);
    }
  }
</style>
