<script lang="ts">
  import type { Snippet } from "svelte";

  type ChipTone = "up" | "down" | "warn" | "neutral";

  let {
    tone = "neutral",
    children
  }: {
    tone?: ChipTone;
    children: Snippet;
  } = $props();
</script>

<span class={`chip ${tone}`}>{@render children()}</span>

<style>
  .chip {
    border: 1px solid color-mix(in srgb, var(--muted) 50%, transparent);
    padding: 3px 6px;
    color: var(--chip-neutral);
    font-size: 11px;
  }

  .chip.up {
    color: var(--up);
  }

  .chip.down {
    color: var(--down);
  }

  .chip.warn {
    border-color: color-mix(in srgb, var(--warning) 75%, transparent);
    color: var(--warning);
  }

  .chip.neutral {
    color: var(--muted);
  }
</style>
