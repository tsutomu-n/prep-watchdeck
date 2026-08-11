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

  onMount(() => {
    selected = readDocumentFontScheme(document.documentElement);
  });

  function selectFontScheme(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    selected = applyDocumentFontScheme(document.documentElement, select.value);
    writeStoredFontScheme(window.localStorage, selected);
    window.dispatchEvent(
      new CustomEvent(FONT_SCHEME_CHANGE_EVENT, {
        detail: { id: selected }
      })
    );
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

  @media (max-width: 48rem), (any-pointer: coarse) {
    select {
      height: var(--control-height-touch);
    }
  }
</style>
