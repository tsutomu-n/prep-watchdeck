<script lang="ts">
  import { logoPlaceholder, resolveAssetLogo, type AssetLogoIdentity } from "$lib/assets/asset-logo";

  type Props = AssetLogoIdentity & { symbol: string; size?: 20 | 22 | 24 | 32 };
  let { symbol, size = 22, assetId, originals, instrumentId, instrumentVersionId }: Props = $props();
  const logo = $derived(resolveAssetLogo({ assetId, originals, instrumentId, instrumentVersionId }));
  let loadedPath = $state<string | null>(null);
  let failedPath = $state<string | null>(null);
  const visible = $derived(Boolean(logo && loadedPath === logo.path && failedPath !== logo.path));
  const placeholder = $derived(logoPlaceholder(symbol));
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
        src={logo.path}
        alt=""
        width={size}
        height={size}
        class:visible
        decoding="async"
        onload={(event) => { loadedPath = event.currentTarget.getAttribute("src"); }}
        onerror={(event) => { failedPath = event.currentTarget.getAttribute("src"); }}
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
