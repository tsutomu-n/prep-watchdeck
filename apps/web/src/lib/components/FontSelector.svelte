<script lang="ts">
  import { onMount } from "svelte";
  import {
    FONT_SCHEME_CHANGE_EVENT,
    applyDocumentFontScheme,
    defaultFontSchemeId,
    fontSchemes,
    readDocumentFontScheme,
    writeStoredFontScheme,
    type FontSchemeId
  } from "$lib/theme/font-scheme";

  let selected = $state<FontSchemeId>(defaultFontSchemeId);
  let storageMessage = $state<string | null>(null);

  onMount(() => {
    const refresh = () => {
      selected = readDocumentFontScheme(document.documentElement);
      storageMessage = null;
    };
    refresh();
    window.addEventListener(FONT_SCHEME_CHANGE_EVENT, refresh);
    return () => window.removeEventListener(FONT_SCHEME_CHANGE_EVENT, refresh);
  });

  function selectFontScheme(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    selected = applyDocumentFontScheme(document.documentElement, select.value);
    let saved = false;
    try {
      saved = writeStoredFontScheme(window.localStorage, selected);
    } catch {
      // Storage itself can be unavailable while display changes remain usable.
    }
    window.dispatchEvent(
      new CustomEvent(FONT_SCHEME_CHANGE_EVENT, {
        detail: { id: selected }
      })
    );
    storageMessage = saved ? null : "保存できないため、再読込するまでこのタブ内だけに適用しています";
  }
</script>

<label class="font-selector">
  <span>フォント</span>
  <select aria-label="フォント" value={selected} onchange={selectFontScheme}>
    {#each fontSchemes as scheme}
      <option value={scheme.id}>{scheme.label}</option>
    {/each}
  </select>
</label>
{#if storageMessage}<small role="status">{storageMessage}</small>{/if}

<style>
  .font-selector {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    align-items: center;
    gap: var(--space-xs);
    min-width: 0;
    color: var(--muted);
    font-size: var(--type-label-caps-size);
    font-weight: var(--type-label-caps-weight);
    line-height: var(--type-label-caps-leading);
  }

  select {
    min-width: 174px;
    height: var(--control-height-dense);
    border: 1px solid var(--line-strong);
    border-radius: var(--radius-xs);
    background: var(--surface);
    color: var(--text);
    padding: 0 var(--space-sm);
    font: inherit;
    font-size: var(--type-body-sm-size);
    cursor: pointer;
  }

  small { display: block; margin-top: var(--space-sm); color: var(--warning); font-size: var(--type-body-sm-size); line-height: 1.5; }

  @media (max-width: 48rem), (any-pointer: coarse) {
    select {
      height: var(--control-height-touch);
    }
  }
</style>
