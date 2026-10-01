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
