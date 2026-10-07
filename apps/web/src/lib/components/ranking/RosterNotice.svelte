<script lang="ts">
  import type { RankingResponse } from "$lib/generated/ranking-response";
  import { rankingTimestamp } from "$lib/market/ranking";

  let { data, now }: { data: RankingResponse; now: number } = $props();
  const health = $derived(data.rosterHealth);
  const expired = $derived(health.catalogObservedAt !== null && now - health.catalogObservedAt > 1_800_000);
  const status = $derived(expired ? "source_stale" : health.status);
  const sourceLabels = {
    source_unavailable: "取扱い名簿の取得元を読み込めません。",
    source_stale: "取扱い名簿の取得元が期限切れです。",
    source_incomplete: "取扱い名簿の取得が不完全です。",
    source_invalid: "取扱い名簿の取得元を検証できません。",
    unconfigured: "取扱い名簿の確認元が設定されていません。"
  };
  const issues = $derived(expired ? null : health.marketDataIssueIds);
</script>

{#if status !== "ready" || data.rosterStale || issues === null || issues.length}
  <aside class="roster-notice" aria-label="取扱い名簿と価格データの状態">
    {#if status === "review_required"}
      <p>取扱い名簿に未反映の変更があります。追加 {health.addedInstrumentIds.length}件・削除 {health.removedInstrumentIds.length}件・契約変更 {health.changedInstrumentIds.length}件。確認済みの名簿で表示しています。</p>
      <details>
        <summary>名簿の変更対象</summary>
        {#if health.addedInstrumentIds.length}<p>追加: {health.addedInstrumentIds.join("、")}</p>{/if}
        {#if health.removedInstrumentIds.length}<p>削除: {health.removedInstrumentIds.join("、")}</p>{/if}
        {#if health.changedInstrumentIds.length}<p>契約変更: {health.changedInstrumentIds.join("、")}</p>{/if}
        <p>その他の取扱い情報の差分も含め、確認が必要です。</p>
      </details>
    {:else if status !== "ready"}
      <p>{sourceLabels[status]} 現在の上場状況は未確認です。</p>
    {:else if data.rosterStale}
      <p>取扱い名簿の最終照合が期限切れです。現在の上場状況は未確認です。</p>
    {/if}
    {#if issues?.length}
      <p>取引所の価格データに欠測・品質警告があります（{issues.length}件）。参照契約のランキング価格とは別の状態です。</p>
      <details><summary>価格データの確認対象</summary><p>{issues.join("、")}</p></details>
    {:else if issues === null}
      <p>元取引所の価格データの品質は未確認です。</p>
    {/if}
    <p class="observed">名簿の最終一致: {rankingTimestamp(data.rosterGeneratedAt)} JST
      {#if health.catalogObservedAt !== null} · Catalog取得: {rankingTimestamp(health.catalogObservedAt)} JST{/if}
    </p>
  </aside>
{/if}

<style>
  .roster-notice { padding: .65rem .85rem; border-left: 3px solid var(--warning-border); background: var(--surface); color: var(--warning); font-size: .8rem; overflow-wrap: anywhere; }
  p { margin: .25rem 0; }
  summary { cursor: pointer; padding-block: .25rem; }
  .observed { color: var(--muted); font-size: .75rem; }
</style>
