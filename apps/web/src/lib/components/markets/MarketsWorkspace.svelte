<script lang="ts">
  import { page } from "$app/state";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import NativeMarkets from "./NativeMarkets.svelte";
  import ReferenceMarkets from "./ReferenceMarkets.svelte";
  import RecentMarkets from "./RecentMarkets.svelte";

  let { data }: { data: { market?: MarketArtifactBundle; marketError?: string } } = $props();
  let mode = $derived(page.url.searchParams.get("mode") === "native" ? "native" : "reference");
</script>

<RecentMarkets />
{#if mode === "reference"}
  <ReferenceMarkets market={data.market ?? null} legacyEntry={page.url.pathname === "/rankings"} />
{:else}
  <NativeMarkets {data} />
{/if}

<footer class="logo-credits"><a href="/asset-logos/credits.html">ロゴの出典・利用条件</a></footer>

<style>
  .logo-credits { max-width: 1900px; margin: 0 auto; padding: var(--space-sm) var(--space-page) var(--space-md); font-size: var(--type-label-caps-size); }
  .logo-credits a { display: inline-flex; align-items: center; min-height: var(--control-height-touch); color: var(--muted); text-underline-offset: 3px; }
  .logo-credits a:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
</style>
