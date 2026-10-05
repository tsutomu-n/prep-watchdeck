<script lang="ts">
  import { onMount } from "svelte";
  import { currentPreferences } from "$lib/theme/workspace-preferences";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import NativeMarkets from "./NativeMarkets.svelte";
  import ReferenceMarkets from "./ReferenceMarkets.svelte";
  import RecentMarkets from "./RecentMarkets.svelte";

  let { data }: { data: { market?: MarketArtifactBundle; marketError?: string } } = $props();
  let startupReady = $state(false);
  let startupError = $state<string | null>(null);
  onMount(() => {
    const initial = currentPreferences();
    // Explicit routes/queries always win over this browser's landing-page preference.
    if (page.url.pathname === "/" && !page.url.search && initial.initialPage === "native") {
      const url = new URL(page.url); url.searchParams.set("mode", "native");
      const origin = page.url.href;
      const timer = setTimeout(async () => {
        try {
          if (page.url.href === origin) await goto(url, { replaceState: true, noScroll: true });
        } catch { startupError = "初期画面へ移動できませんでした。メニューから画面を選んでください。"; }
        finally { startupReady = true; }
      }, 0);
      return () => clearTimeout(timer);
    }
    startupReady = true;
  });
  let mode = $derived(page.url.searchParams.get("mode") === "native" ? "native" : "reference");
</script>

{#if startupError}<p role="status">{startupError}</p>{/if}
{#if startupReady}
<RecentMarkets />
{#if mode === "reference"}
  <ReferenceMarkets market={data.market ?? null} legacyEntry={page.url.pathname === "/rankings"} />
{:else}
  <NativeMarkets {data} />
{/if}

{:else}<p role="status">表示設定を読み込んでいます。</p>{/if}

<footer class="logo-credits"><a href="/asset-logos/credits.html">ロゴの出典・利用条件</a></footer>

<style>
  .logo-credits { max-width: 1900px; margin: 0 auto; padding: var(--space-sm) var(--space-page) var(--space-md); font-size: var(--type-label-caps-size); }
  .logo-credits a { display: inline-flex; align-items: center; min-height: var(--control-height-touch); color: var(--muted); text-underline-offset: 3px; }
  .logo-credits a:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
</style>
