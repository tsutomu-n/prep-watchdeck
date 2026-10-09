<script lang="ts">
  import { onMount } from "svelte";
  import { currentPreferences } from "$lib/theme/workspace-preferences";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import type { MarketArtifactBundle } from "$lib/server/market-artifact-repository";
  import { loadNativeMarkets, loadReferenceMarkets } from "./lazy-surfaces";
  import RecentMarkets from "./RecentMarkets.svelte";

  let { data }: { data: { market?: MarketArtifactBundle; marketError?: string } } = $props();
  let startupReady = $state(false);
  let startupError = $state<string | null>(null);
  let NativeMarkets = $state.raw<typeof import("./NativeMarkets.svelte").default | null>(null);
  let ReferenceMarkets = $state.raw<typeof import("./ReferenceMarkets.svelte").default | null>(null);
  let surfaceError = $state<"native" | "reference" | null>(null);
  let mode: "native" | "reference" = $derived(
    page.url.searchParams.get("mode") === "native" ? "native" : "reference"
  );
  let surfaceName = $derived(mode === "native" ? "取引所別" : "ランキング");

  onMount(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function prefetchNavigation(event: Event) {
      if (!(event.target instanceof Element)) return;
      const link = event.target.closest<HTMLAnchorElement>('nav[aria-label="メインメニュー"] a[href]');
      if (!link) return;
      const target = new URL(link.href);
      if (target.origin !== page.url.origin || !["/", "/rankings"].includes(target.pathname)) return;
      const targetMode = target.searchParams.get("mode") === "native" ? "native" : "reference";
      if (targetMode === mode) return;
      // Importing code never mounts the inactive surface or starts its data requests/polls.
      void (targetMode === "native" ? loadNativeMarkets() : loadReferenceMarkets()).catch(() => {});
    }
    const events = ["pointerover", "pointerdown", "focusin"];
    for (const event of events) document.addEventListener(event, prefetchNavigation, { passive: true });

    const initial = currentPreferences();
    // Explicit routes/queries always win over this browser's landing-page preference.
    if (page.url.pathname === "/" && !page.url.search && initial.initialPage === "native") {
      const url = new URL(page.url); url.searchParams.set("mode", "native");
      const origin = page.url.href;
      timer = setTimeout(async () => {
        try {
          if (!cancelled && page.url.href === origin) await goto(url, { replaceState: true, noScroll: true });
        } catch {
          if (!cancelled) startupError = "初期画面へ移動できませんでした。メニューから画面を選んでください。";
        } finally {
          if (!cancelled) startupReady = true;
        }
      }, 0);
    } else {
      startupReady = true;
    }
    return () => {
      cancelled = true;
      clearTimeout(timer);
      for (const event of events) document.removeEventListener(event, prefetchNavigation);
    };
  });

  $effect(() => {
    if (!startupReady) return;
    const requestedMode = mode;
    let cancelled = false;
    surfaceError = null;
    if (requestedMode === "native") {
      void loadNativeMarkets().then((module) => {
        if (!cancelled) NativeMarkets = module.default;
      }).catch(() => { if (!cancelled) surfaceError = requestedMode; });
    } else {
      void loadReferenceMarkets().then((module) => {
        if (!cancelled) ReferenceMarkets = module.default;
      }).catch(() => { if (!cancelled) surfaceError = requestedMode; });
    }
    return () => { cancelled = true; };
  });
</script>

{#if startupError}<p role="status">{startupError}</p>{/if}
{#if startupReady}
<RecentMarkets />
{#if mode === "reference" && ReferenceMarkets}
  <ReferenceMarkets market={data.market ?? null} legacyEntry={page.url.pathname === "/rankings"} />
{:else if mode === "native" && NativeMarkets}
  <NativeMarkets {data} />
{:else}
  <main class="surface-loading" aria-label={surfaceName}>
    <h1>{surfaceName}</h1>
    {#if surfaceError === mode}
      <p role="alert">画面を読み込めませんでした。通信状態を確認して再読み込みしてください。</p>
      <button type="button" onclick={() => window.location.reload()}>画面を再読み込み</button>
    {:else}
      <p role="status">{surfaceName}の画面を読み込んでいます。</p>
    {/if}
  </main>
{/if}

{:else}
  <main class="surface-loading" aria-label="Markets">
    <p role="status">表示設定を読み込んでいます。</p>
  </main>
{/if}

<footer class="logo-credits"><a href="/asset-logos/credits.html">ロゴの出典・利用条件</a></footer>

<style>
  .surface-loading { max-width: 1900px; min-height: 60vh; margin: 0 auto; padding: var(--space-lg) var(--space-page); }
  .surface-loading h1 { margin: 0; font-size: var(--type-title-lg-size); }
  .surface-loading p { color: var(--muted); }
  .surface-loading button { min-height: var(--control-height-touch); }
  .logo-credits { max-width: 1900px; margin: 0 auto; padding: var(--space-sm) var(--space-page) var(--space-md); font-size: var(--type-label-caps-size); }
  .logo-credits a { display: inline-flex; align-items: center; min-height: var(--control-height-touch); color: var(--muted); text-underline-offset: 3px; }
  .logo-credits a:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
</style>
