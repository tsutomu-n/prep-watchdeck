<script lang="ts">
  import { tick } from "svelte";
  import { logoPlaceholder, resolveAssetLogo, type AssetLogoIdentity } from "$lib/assets/asset-logo";

  type Props = AssetLogoIdentity & { symbol: string; size?: 20 | 22 | 24 | 32 };
  let { symbol, size = 22, assetId, originals, instrumentId, instrumentVersionId }: Props = $props();
  const logo = $derived(resolveAssetLogo({ assetId, originals, instrumentId, instrumentVersionId }));
  let loadedPath = $state<string | null>(null);
  let failedPath = $state<string | null>(null);
  const visible = $derived(Boolean(logo && loadedPath === logo.path && failedPath !== logo.path));
  const placeholder = $derived(logoPlaceholder(symbol));

  function readCompletedImage(image: HTMLImageElement) {
    let active = true;
    // Finish mounting before publishing readiness, including immediately cached images.
    // The decode promise handles completion even when no load event reaches this instance.
    void tick().then(async () => {
      if (!active) return;
      try { await image.decode(); } catch { /* A failed decode is inspected below. */ }
      if (!active || !image.complete) return;
      const path = image.getAttribute("src");
      if (image.naturalWidth > 0) loadedPath = path;
      else failedPath = path;
    });
    return { destroy() { active = false; } };
  }
</script>

<span
  class="asset-icon"
  class:large={size === 32}
  aria-hidden="true"
  style:width={`${size}px`}
  style:height={`${size}px`}
  data-testid="asset-icon"
  data-logo-state={visible ? "verified" : "fallback"}
  data-asset-id={visible ? logo?.assetId : undefined}
>
  <span class="placeholder" class:concealed={visible}>{placeholder}</span>
  {#if logo && failedPath !== logo.path}
    {#key logo.path}
      <img
        use:readCompletedImage
        src={logo.path}
        alt=""
        width={size}
        height={size}
        class:visible
        decoding="async"
      />
    {/key}
  {/if}
</span>

<style>
  .asset-icon {
    display: inline-grid;
    position: relative;
    place-items: center;
    flex: none;
    overflow: hidden;
    border-radius: 50%;
    background: var(--panel-strong);
    color: var(--text);
    font: 600 9px/1 var(--font-sans);
    vertical-align: middle;
    box-sizing: border-box;
  }
  .large { font-size: 12px; }
  .placeholder { letter-spacing: 0; }
  .concealed { visibility: hidden; }
  img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
  img.visible { opacity: 1; }
</style>
