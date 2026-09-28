<script lang="ts">
  import type { PageProps } from "./$types";
  import MarketsWorkspace from "$lib/components/markets/MarketsWorkspace.svelte";
  let { data }: PageProps = $props();
</script>

<MarketsWorkspace {data} />
