<script lang="ts">
  import { page } from "$app/state";
  import { initializePreferences } from "$lib/theme/workspace-preferences";
  import { onMount } from "svelte";
  import "$lib/styles/watchdeck-theme.css";
  import {
    COLOR_SCHEME_CHANGE_EVENT,
    COLOR_SCHEME_STORAGE_KEY,
    applyDocumentColorScheme
  } from "$lib/theme/color-scheme";
  import {
    FONT_SCHEME_CHANGE_EVENT,
    FONT_SCHEME_STORAGE_KEY,
    applyDocumentFontScheme
  } from "$lib/theme/font-scheme";

  let { children } = $props();
  let isMarketPage = $derived(page.url.pathname === "/" || page.url.pathname === "/rankings");
  let nativeMode = $derived(isMarketPage && page.url.searchParams.get("mode") === "native");
  let settingsPage = $derived(page.url.pathname === "/settings");

  onMount(initializePreferences);

  onMount(() => {
    function syncDisplayPreferences(event: StorageEvent) {
      if (event.key === COLOR_SCHEME_STORAGE_KEY || event.key === null) {
        const id = applyDocumentColorScheme(document.documentElement, event.newValue);
        window.dispatchEvent(new CustomEvent(COLOR_SCHEME_CHANGE_EVENT, { detail: { id } }));
      }
      if (event.key === FONT_SCHEME_STORAGE_KEY || event.key === null) {
        const id = applyDocumentFontScheme(document.documentElement, event.newValue);
        window.dispatchEvent(new CustomEvent(FONT_SCHEME_CHANGE_EVENT, { detail: { id } }));
      }
    }
    window.addEventListener("storage", syncDisplayPreferences);
    return () => window.removeEventListener("storage", syncDisplayPreferences);
  });
</script>

<nav class="workspace-navigation" aria-label="メインメニュー">
  <a href="/?mode=reference" data-sveltekit-preload-data="off" aria-current={isMarketPage && !nativeMode ? "page" : undefined}>ランキング</a>
  <a href="/?mode=native" data-sveltekit-preload-data="off" aria-current={nativeMode ? "page" : undefined}>取引所別</a>
  <a href="/attention" aria-current={page.url.pathname === "/attention" ? "page" : undefined}>注目</a>
  <a href="/settings" aria-current={settingsPage ? "page" : undefined}>設定</a>
</nav>
{@render children()}

<style>
  .workspace-navigation {
    display: flex;
    gap: var(--space-sm);
    padding: var(--space-sm) var(--space-page);
    border-bottom: 1px solid var(--line-strong);
    background: var(--panel-solid);
  }
  a {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: var(--control-height-touch);
    padding: 0 var(--space-lg);
    color: var(--muted);
    text-decoration: none;
    border: 1px solid var(--line);
    border-radius: var(--radius-xs);
    font-weight: 700;
  }
  a[aria-current="page"] {
    color: var(--focus-on);
    background: var(--focus);
    border-color: var(--focus);
  }
  @media (max-width: 48rem) {
    a { flex: 1; min-width: 0; padding: 0 var(--space-xs); }
  }
</style>
