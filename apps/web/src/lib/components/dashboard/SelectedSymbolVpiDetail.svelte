<script lang="ts">
  import { formatDateTime as fmtDate, formatNumber as fmt } from "$lib/market/format";
  import {
    vpiDataQualityLabel,
    vpiFundingStateLabel,
    vpiOpenInterestStateLabel,
    vpiReasonLabel,
    vpiRiskLabel,
    vpiStateLabel,
    type VpiLitePlusItem
  } from "$lib/market/vpi-lite-plus";

  let { item }: { item: VpiLitePlusItem } = $props();
</script>

<section class="vpi-detail" aria-label="選択銘柄 VPI補助詳細">
  <header>
    <div>
      <h3>選択銘柄 VPI補助</h3>
      <p>補助値 {fmt(item.score)} / 100</p>
    </div>
    <strong>{vpiStateLabel(item.state)}</strong>
  </header>

  <dl>
    <div>
      <dt>データ状態</dt>
      <dd>{vpiDataQualityLabel(item.dataQuality)}</dd>
    </div>
    <div>
      <dt>Funding</dt>
      <dd>{vpiFundingStateLabel(item.fundingState)}</dd>
    </div>
    <div>
      <dt>OI availability</dt>
      <dd>{vpiOpenInterestStateLabel(item.openInterestState)}</dd>
    </div>
    <div>
      <dt>データ時点</dt>
      <dd>{item.dataAsOf === null ? "未取得" : fmtDate(item.dataAsOf)}</dd>
    </div>
  </dl>

  {#if item.reasonCodes.length > 0}
    <div class="code-group">
      <h4>活動理由</h4>
      <div>
        {#each item.reasonCodes as code}
          <span>{vpiReasonLabel(code)}</span>
        {/each}
      </div>
    </div>
  {/if}

  {#if item.riskTagCodes.length > 0}
    <div class="code-group risk">
      <h4>注意</h4>
      <div>
        {#each item.riskTagCodes as code}
          <span>{vpiRiskLabel(code)}</span>
        {/each}
      </div>
    </div>
  {/if}
</section>

<style>
  .vpi-detail {
    padding: var(--space-md);
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel);
  }

  header {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: var(--space-md);
  }

  h3,
  h4,
  p {
    margin: 0;
  }

  h3 {
    font-size: 12px;
  }

  header p {
    margin-top: var(--space-xs);
    color: var(--subtle);
    font-size: 11px;
  }

  header strong {
    color: var(--chip-neutral);
    font-size: 12px;
    text-align: right;
  }

  dl {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 1px;
    margin: var(--space-sm) 0 0;
    background: var(--line);
  }

  dl div {
    min-width: 0;
    padding: var(--space-sm);
    background: var(--panel-strong);
  }

  dt {
    color: var(--muted);
    font-size: 10px;
  }

  dd {
    margin: 3px 0 0;
    overflow-wrap: anywhere;
    color: var(--text);
    font-size: 11px;
  }

  .code-group {
    margin-top: var(--space-sm);
  }

  h4 {
    color: var(--subtle);
    font-size: 10px;
  }

  .code-group > div {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-xs);
    margin-top: var(--space-xs);
  }

  .code-group span {
    border: 0;
    padding: 0;
    color: var(--chip-neutral);
    font-size: 10px;
    line-height: 1.25;
  }

  .code-group.risk span {
    color: var(--warning);
  }
</style>
