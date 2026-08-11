<script lang="ts">
  import { onMount } from "svelte";
  import {
    COLOR_SCHEME_CHANGE_EVENT,
    applyDocumentColorScheme,
    colorSchemeGroups,
    colorSchemes,
    defaultColorSchemeId,
    readDocumentColorScheme,
    writeStoredColorScheme,
    type ColorSchemeId
  } from "$lib/theme/color-scheme";

  let selected = $state<ColorSchemeId>(defaultColorSchemeId);
  let selectedScheme = $derived(
    colorSchemes.find((scheme) => scheme.id === selected) ?? colorSchemes[0]
  );
  let selectedModeLabel = $derived(selectedScheme.mode === "dark" ? "ダーク" : "ライト");

  onMount(() => {
    selected = readDocumentColorScheme(document.documentElement);
  });

  function selectColorScheme(event: Event) {
    const select = event.currentTarget as HTMLSelectElement;
    selected = applyDocumentColorScheme(document.documentElement, select.value);
    writeStoredColorScheme(window.localStorage, selected);
    window.dispatchEvent(
      new CustomEvent(COLOR_SCHEME_CHANGE_EVENT, {
        detail: { id: selected }
      })
    );
  }
</script>

<label class="theme-selector">
  <span class="theme-selector__title">
    <span>配色</span>
    <strong aria-label={`現在のテーマ種別: ${selectedModeLabel}`}>
      {selectedScheme.mode.toUpperCase()}
    </strong>
  </span>
  <select aria-label="配色" value={selected} onchange={selectColorScheme}>
    {#each colorSchemeGroups as group}
      <optgroup label={group.label}>
        {#each group.schemes as scheme}
          <option value={scheme.id}>{scheme.label}</option>
        {/each}
      </optgroup>
    {/each}
  </select>
</label>

<style>
  .theme-selector {
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

  .theme-selector__title {
    display: flex;
    align-items: center;
    gap: var(--space-xs);
    white-space: nowrap;
  }

  .theme-selector__title strong {
    min-width: 38px;
    box-sizing: border-box;
    border: 1px solid var(--line-strong);
    background: var(--panel-strong);
    color: var(--text);
    padding: var(--space-xxs) var(--space-xs);
    font-size: 9px;
    line-height: 1;
    text-align: center;
  }

  select {
    min-width: 132px;
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
