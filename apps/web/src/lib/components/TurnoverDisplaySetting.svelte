<script lang="ts">
  import { onMount } from "svelte";
  import { DEFAULT_TURNOVER_DECIMALS, formatTurnover } from "$lib/market/turnover-format";
  import { setTurnoverDecimals, subscribeTurnoverDecimals } from "$lib/theme/display-preferences";

  let decimals = $state(DEFAULT_TURNOVER_DECIMALS);
  let storageMessage = $state<string | null>(null);
  onMount(() => subscribeTurnoverDecimals(value => { decimals = value; storageMessage = null; }));

  function change(event: Event) {
    decimals = Number((event.currentTarget as HTMLSelectElement).value);
    storageMessage = setTurnoverDecimals(decimals) ? null
      : "保存できないため、再読込するまでこのタブ内だけに適用しています";
  }
</script>

<div class="turnover-setting">
  <label>
    <span>売買代金の表示小数桁</span>
    <select value={decimals} onchange={change} aria-label="売買代金の表示小数桁" aria-describedby="turnover-display-help">
      {#each [0, 1, 2, 3, 4] as digits}<option value={digits}>{digits}桁{digits === 2 ? "（標準）" : ""}</option>{/each}
    </select>
  </label>
  <p id="turnover-display-help">ランキングの一覧・詳細・過去日比較に適用します。末尾の不要なゼロは省きます。価格と計算・順位・絞り込みは変わりません。</p>
  <p class="preview">表示例：<output>{formatTurnover(108129798.20669937, decimals)}</output> USDT</p>
  {#if storageMessage}<p role="status" class="warning">{storageMessage}</p>{/if}
</div>

<style>
  label { display: flex; flex-direction: column; gap: var(--space-sm); color: var(--subtle); }
  select { min-height: var(--control-height-touch); width: 100%; padding: var(--space-sm); font: inherit; color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); border-radius: var(--radius-xs); }
  p { margin: var(--space-sm) 0 0; font-size: var(--type-body-sm-size); line-height: 1.65; color: var(--muted); }
  .preview { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  output { color: var(--text); }
  .warning { color: var(--warning); }
</style>
