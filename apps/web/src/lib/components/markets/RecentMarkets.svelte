<script lang="ts">
  import { onMount } from "svelte";
  import { readRecentMarkets, RECENT_CHANGE_EVENT, type RecentMarket } from "$lib/market/recent-markets";
  import AssetIcon from "$lib/components/AssetIcon.svelte";
  let recent = $state<RecentMarket[]>([]);
  onMount(() => {
    const refresh = () => {
      try { recent = readRecentMarkets(window.localStorage); }
      catch { recent = []; }
    };
    refresh();
    window.addEventListener(RECENT_CHANGE_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(RECENT_CHANGE_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  });
</script>

<details class="recent">
  <summary>最近見た {recent.length} 件</summary>
  {#if recent.length}
    <ul>{#each recent as item (item.key)}
      <li><a href={item.href}><AssetIcon symbol={item.label} /><span>{item.label}</span></a></li>
    {/each}</ul>
  {:else}<p>閲覧履歴はこの端末にはありません。</p>{/if}
</details>

<style>
  .recent { padding: var(--space-sm) var(--space-md); background: var(--panel); }
  summary { cursor: pointer; color: var(--text); }
  ul { display: flex; flex-wrap: wrap; gap: var(--space-sm); list-style: none; padding: var(--space-sm) 0; margin: 0; }
  li { min-width: 0; }
  a { display: flex; align-items: center; gap: var(--space-xs); min-height: var(--control-height-touch); color: var(--focus); }
  a > span { min-width: 0; overflow-wrap: anywhere; }
  p { color: var(--muted); }
</style>
