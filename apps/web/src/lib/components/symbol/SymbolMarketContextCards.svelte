<script lang="ts">
  import SymbolChip from "$lib/components/symbol/SymbolChip.svelte";
  import type { ScannerRowDTO } from "$lib/generated/scanner-snapshot";
  import { formatNumber as fmt } from "$lib/market/format";
  import { changeTone, codeLabel, userRule74hLabel } from "$lib/market/labels";
  import type { Range24h } from "$lib/market/row-analysis";

  let { row, range }: { row: ScannerRowDTO; range: Range24h | null } = $props();
</script>

<section id="symbol-market-context" class="intel-card context-section" data-symbol-workspace-section tabindex="-1">
  <h2>24h レンジ</h2>
  {#if range}
    <div class="range-track" aria-hidden="true">
      <span class="range-marker" style={`left: ${range.positionPct}%`}></span>
    </div>
    <dl class="range-values">
      <div>
        <dt>安値</dt>
        <dd>{fmt(range.low)}</dd>
      </div>
      <div>
        <dt>現在</dt>
        <dd>{fmt(range.close)}</dd>
      </div>
      <div>
        <dt>高値</dt>
        <dd>{fmt(range.high)}</dd>
      </div>
      <div>
        <dt>位置</dt>
        <dd>{fmt(range.positionPct, "%")}</dd>
      </div>
    </dl>
  {:else}
    <p class="empty">レンジ未取得</p>
  {/if}
</section>

<section class="intel-card context-section" data-symbol-workspace-section>
  <h2>74h 条件</h2>
  <dl class="fact-list">
    <div>
      <dt>価格変化</dt>
      <dd class={changeTone(row.priceChange74hPct)}>{fmt(row.priceChange74hPct, "%")}</dd>
    </div>
    <div>
      <dt>現在24h代金</dt>
      <dd>{fmt(row.turnoverCurrent24hUsdt)}</dd>
    </div>
    <div>
      <dt>74h前24h代金</dt>
      <dd>{fmt(row.turnover24hEnding74hAgoUsdt)}</dd>
    </div>
    <div>
      <dt>代金変化</dt>
      <dd class={changeTone(row.volumeChange74h24hPct)}>{fmt(row.volumeChange74h24hPct, "%")}</dd>
    </div>
    <div>
      <dt>ユーザー条件</dt>
      <dd>{userRule74hLabel(row.userRule74hMatched)}</dd>
    </div>
  </dl>
</section>

<section class="intel-card context-section" data-symbol-workspace-section>
  <h2>品質と市場条件</h2>
  <dl class="fact-list">
    <div>
      <dt>データ網羅率</dt>
      <dd>{fmt((row.coverageRatio ?? 0) * 100, "%")}</dd>
    </div>
    <div>
      <dt>欠損本数</dt>
      <dd>{fmt(row.missingBarCount)}</dd>
    </div>
    <div>
      <dt>ゼロ出来高比率</dt>
      <dd>{fmt(row.zeroVolumeBarRatio, "%")}</dd>
    </div>
    <div>
      <dt>BTC相対15m</dt>
      <dd class={changeTone(row.btcRelative15m)}>{fmt(row.btcRelative15m, "%")}</dd>
    </div>
    <div>
      <dt>funding</dt>
      <dd>{String(row.fundingBias ?? "未取得")}</dd>
    </div>
  </dl>
</section>

<section class="intel-card context-section" data-symbol-workspace-section>
  <h2>理由とリスク</h2>
  <div class="chips">
    {#each row.reasonCodes ?? [] as code}
      <SymbolChip>{codeLabel(code)}</SymbolChip>
    {:else}
      <SymbolChip>理由コードなし</SymbolChip>
    {/each}
    {#each row.riskTagCodes ?? [] as code}
      <SymbolChip tone="warn">{codeLabel(code)}</SymbolChip>
    {:else}
      <SymbolChip>リスクタグなし</SymbolChip>
    {/each}
  </div>
</section>

<style>
  .intel-card {
    min-width: 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    padding: 12px;
  }

  .intel-card h2 {
    margin: 0;
    font-size: 15px;
  }

  .range-values,
  .fact-list {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0;
    background: transparent;
  }

  .range-values div,
  .fact-list div {
    min-width: 0;
    padding: 10px;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .fact-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-top: 10px;
  }

  .range-values {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    margin: 0;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }

  .range-values div:not(:last-child) {
    border-right: 1px solid var(--line);
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
    margin: 5px 0 0;
    overflow-wrap: anywhere;
    font-size: 15px;
    font-weight: 850;
  }

  .range-track {
    position: relative;
    height: 10px;
    margin: 14px 0 10px;
    border: 1px solid color-mix(in srgb, var(--muted) 45%, transparent);
    background: var(--line-strong);
  }

  .range-marker {
    position: absolute;
    top: -5px;
    width: 2px;
    height: 20px;
    background: var(--text);
    box-shadow: 0 0 0 1px var(--bg-alt);
    transform: translateX(-1px);
  }

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 10px;
  }

  .good {
    color: var(--up);
  }

  .risk {
    color: var(--down);
  }

  .empty {
    margin: 10px 0 0;
    color: var(--muted);
    font-size: 13px;
  }

  @media (max-width: 720px) {
    .fact-list,
    .range-values {
      grid-template-columns: 1fr;
    }

    .fact-list div:nth-child(odd),
    .range-values div:not(:last-child) {
      border-right: 0;
    }

    .fact-list div:nth-child(n + 2),
    .range-values div:nth-child(n + 2) {
      border-top: 1px solid var(--line);
    }
  }
</style>
