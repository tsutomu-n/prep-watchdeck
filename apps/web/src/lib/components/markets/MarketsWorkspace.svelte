<script lang="ts">
  import { page } from "$app/state";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import NativeMarkets from "./NativeMarkets.svelte";
  import ReferenceMarkets from "./ReferenceMarkets.svelte";
  import RecentMarkets from "./RecentMarkets.svelte";

  let { data }: { data: { market?: MarketArtifactBundle; marketError?: string } } = $props();
  let mode = $derived(page.url.searchParams.get("mode") === "native" ? "native" : "reference");
</script>

<nav class="market-modes" aria-label="Marketsの表示">
  <a href="/?mode=reference" aria-current={mode === "reference" ? "page" : undefined}>参照市場</a>
  <a href="/?mode=native" aria-current={mode === "native" ? "page" : undefined}>取引所別</a>
</nav>
<RecentMarkets />
{#if mode === "reference"}
  <ReferenceMarkets market={data.market ?? null} legacyEntry={page.url.pathname === "/rankings"} />
{:else}
  <NativeMarkets {data} />
{/if}

<style>
  .market-modes {
    display: flex;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-md);
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel);
  }
  a {
    display: inline-flex;
    align-items: center;
    min-height: var(--control-height-touch);
    padding: 0 var(--space-md);
    color: var(--muted);
    text-decoration: none;
    border: 1px solid var(--line);
    font-weight: 700;
  }
  a[aria-current="page"] {
    color: var(--focus-on);
    background: var(--focus);
    border-color: var(--focus);
  }
</style>
