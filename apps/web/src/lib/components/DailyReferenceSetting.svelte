<script lang="ts">
  import { onMount } from "svelte";
  import {
    DEFAULT_REFERENCE_TIME,
    REFERENCE_TIME_STORAGE_KEY,
    isReferenceTime,
    readStoredReferenceTime,
    writeStoredReferenceTime
  } from "$lib/market/price-change";

  let { value = $bindable(DEFAULT_REFERENCE_TIME), ready = $bindable(false) } = $props<{
    value?: string;
    ready?: boolean;
  }>();
  let storageMessage = $state<string | null>(null);

  onMount(() => {
    try {
      value = readStoredReferenceTime(window.localStorage);
    } catch {
      value = DEFAULT_REFERENCE_TIME;
    }
    ready = true;
    function sync(event: StorageEvent) {
      if (event.key !== REFERENCE_TIME_STORAGE_KEY && event.key !== null) return;
      value = isReferenceTime(event.newValue) ? event.newValue : DEFAULT_REFERENCE_TIME;
      storageMessage = null;
    }
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  });

  function changeReference(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    if (!isReferenceTime(input.value)) {
      input.value = value;
      return;
    }
    value = input.value;
    let saved = false;
    try {
      saved = writeStoredReferenceTime(window.localStorage, value);
    } catch {
      // Storage itself can be inaccessible in a restricted browser context.
    }
    storageMessage = saved ? null : "保存できないため、この画面だけに適用しています";
  }
</script>

<div class="daily-reference-setting">
  <label>
    <span>騰落率の基準 <strong>JST</strong></span>
    <input
      type="time"
      step="60"
      required
      aria-label="騰落率の基準時刻（日本時間）"
      title="指定した日本時間の直前の1分足終値を基準にします"
      {value}
      onchange={changeReference}
    />
  </label>
  {#if storageMessage}<small role="status">{storageMessage}</small>{/if}
</div>

<style>
  .daily-reference-setting { min-width: 0; }
  label { display: flex; align-items: center; gap: var(--space-xs); color: var(--muted); font-size: var(--type-label-caps-size); }
  label > span { white-space: nowrap; }
  strong { color: var(--subtle); font: inherit; }
  input { min-width: 7rem; height: var(--control-height-dense); border: 1px solid var(--line-strong); border-radius: var(--radius-xs); background: var(--surface); color: var(--text); padding: 0 var(--space-sm); font: inherit; font-size: var(--type-body-sm-size); }
  small { display: block; max-width: 19rem; margin-top: var(--space-xs); color: var(--warning); font-size: var(--type-label-caps-size); }
  @media (max-width: 48rem), (any-pointer: coarse) {
    label { justify-content: space-between; }
    input { height: var(--control-height-touch); flex: 1; }
  }
</style>
