<script lang="ts">
  import type { Snippet } from "svelte";

  type DetailTone = "good" | "warn" | "risk" | null;

  let {
    group,
    title,
    description,
    badge,
    tone = null,
    onToggle,
    children
  }: {
    group: string;
    title: string;
    description: string;
    badge: string;
    tone?: DetailTone;
    onToggle?: (open: boolean) => void;
    children: Snippet;
  } = $props();
</script>

<details
  class="detail-group"
  data-detail-group={group}
  ontoggle={(event) => onToggle?.(event.currentTarget.open)}
>
  <summary>
    <span>
      <strong>{title}</strong>
      <small>{description}</small>
    </span>
    <em class:good={tone === "good"} class:warn={tone === "warn"} class:risk={tone === "risk"}>{badge}</em>
  </summary>
  {@render children()}
</details>

<style>
  .detail-group {
    border-bottom: 1px solid var(--line);
    background: color-mix(in srgb, var(--bg-alt) 88%, transparent);
  }

  .detail-group > summary {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto 18px;
    align-items: center;
    gap: 8px;
    min-height: 42px;
    padding: 0 10px 0 12px;
    cursor: pointer;
    list-style: none;
  }

  .detail-group > summary::-webkit-details-marker {
    display: none;
  }

  .detail-group > summary::after {
    content: "+";
    display: grid;
    place-items: center;
    width: 18px;
    height: 18px;
    border: 1px solid color-mix(in srgb, var(--muted) 42%, transparent);
    color: var(--muted);
    font-size: 13px;
    line-height: 1;
  }

  .detail-group[open] > summary {
    border-bottom: 1px solid color-mix(in srgb, var(--muted) 20%, transparent);
  }

  .detail-group[open] > summary::after {
    content: "-";
    border-color: var(--focus);
    color: var(--focus);
  }

  .detail-group > summary:focus-visible {
    outline: var(--focus-ring-width) solid var(--focus);
    outline-offset: -2px;
  }

  .detail-group > summary:active {
    background: var(--panel-strong);
  }

  .detail-group > summary strong,
  .detail-group > summary small {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .detail-group > summary strong {
    color: var(--text);
    font-size: 13px;
  }

  .detail-group > summary small {
    margin-top: 2px;
    color: var(--muted);
    font-size: 10px;
  }

  .detail-group > summary em {
    border: 1px solid color-mix(in srgb, var(--muted) 38%, transparent);
    padding: 3px 6px;
    color: var(--muted);
    font-size: 10px;
    font-style: normal;
    white-space: nowrap;
  }

  .detail-group > summary em.good {
    border-color: var(--quality-good);
    color: var(--quality-good);
  }

  .detail-group > summary em.warn {
    border-color: var(--warning-border);
    color: var(--warning);
  }

  .detail-group > summary em.risk {
    border-color: var(--quality-risk);
    color: var(--quality-risk);
  }

  @media (max-width: 48rem), (any-pointer: coarse) {
    .detail-group > summary {
      min-height: var(--control-height-touch);
    }
  }

  @media (hover: hover) and (pointer: fine) {
    .detail-group > summary:hover {
      background: var(--panel-strong);
    }
  }
</style>
