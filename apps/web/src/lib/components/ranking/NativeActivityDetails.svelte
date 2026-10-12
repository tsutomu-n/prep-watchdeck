<script lang="ts">
  import type { ActivitySample, ActivityValue, NativeActivityRow } from "$lib/generated/native-activity";
  import { displayNumber } from "$lib/market/number-display";
  import { formatPriceChange } from "$lib/market/price-change";
  import { rankingTimestamp } from "$lib/market/ranking";
  import { DEFAULT_TURNOVER_DECIMALS, formatTurnover } from "$lib/market/turnover-format";
  import { preferences } from "$lib/theme/workspace-preferences";

  let { row, reason, decimals = DEFAULT_TURNOVER_DECIMALS }: {
    row: NativeActivityRow | null; reason: string | null; decimals?: number;
  } = $props();
  const windows = $derived(row ? [row.windows["15m"], row.windows["1h"]].filter(Boolean) : []);

  function ready(value: ActivityValue): number | null {
    return value.status === "ready" && typeof value.value === "number" && Number.isFinite(value.value) ? value.value : null;
  }

  function label(value: ActivityValue, kind: "turnover" | "ratio" | "percent", compact = false): string {
    const amount = ready(value);
    if (amount === null) return {
      ready: "値なし", history_missing: "履歴不足", invalid_data: "入力不整合",
      no_baseline: "比較基準なし", low_baseline: "比較基準が少額"
    }[value.status];
    if (kind === "turnover") return formatTurnover(amount, decimals, compact);
    return kind === "ratio" ? `${displayNumber(amount, $preferences.ratioDecimals)}×`
      : formatPriceChange(amount, $preferences.percentDecimals);
  }

  function sampleTitle(sample: ActivitySample): string {
    return `${rankingTimestamp(Date.parse(sample.startAt))} → ${rankingTimestamp(Date.parse(sample.endAt))} JST` +
      ` · 売買代金 ${label(sample.turnover, "turnover")} USDT · 価格 ${label(sample.priceChangePct, "percent")}`;
  }
</script>

<section class="native-activity-details" aria-label="Bitgetの短期アクティビティ" data-testid="native-activity-details">
  <h3>Bitget 短期アクティビティ <span>売買代金 USDT</span></h3>
  {#if !row}
    <p class="unavailable" data-testid="native-activity-unavailable">{reason ?? "短期データなし"}</p>
  {:else}
    <p class="source">Bitget {row.sourceSymbol} · 完了済み1分足から集計</p>
    <table class="metrics">
      <caption>最新の15分・1時間区間</caption>
      <colgroup><col class="period-column" /><col class="turnover-column" /><col /><col /><col /></colgroup>
      <thead><tr><th scope="col">区間</th><th scope="col">売買代金</th><th scope="col">価格</th><th scope="col">普段比</th><th scope="col">前区間比</th></tr></thead>
      <tbody>
        {#each windows as window}
          {@const price = ready(window.current.priceChangePct)}
          {@const ratio = ready(window.relativeRatio)}
          <tr>
            <th scope="row">{window.minutes === 15 ? "15m" : "1h"}</th>
            <td class:missing={ready(window.current.turnover) === null} title={`${label(window.current.turnover, "turnover")} USDT`}>{label(window.current.turnover, "turnover", $preferences.turnoverNotation === "compact")}</td>
            <td class:up={price !== null && price > 0} class:down={price !== null && price < 0} class:missing={price === null}>{label(window.current.priceChangePct, "percent")}</td>
            <td class:surge={ratio !== null && ratio >= $preferences.surgeRatio} class:missing={ratio === null}>{label(window.relativeRatio, "ratio")}</td>
            <td class:missing={ready(window.previousChangePct) === null}>{label(window.previousChangePct, "percent")}</td>
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="cutoffs">
      {#each windows as window}
        <p><b>{window.minutes === 15 ? "15m" : "1h"}</b> {rankingTimestamp(Date.parse(window.current.startAt))} → {rankingTimestamp(Date.parse(window.current.endAt))} JST</p>
      {/each}
    </div>
    <table class="history">
      <caption>直近4区間の売買代金 · 古い順、右端が現在</caption>
      <colgroup><col class="period-column" /><col /><col /><col /><col /></colgroup>
      <thead><tr><th scope="col">区間</th><th scope="col">3区間前</th><th scope="col">2区間前</th><th scope="col">前区間</th><th scope="col">現在</th></tr></thead>
      <tbody>
        {#each windows as window}
          <tr>
            <th scope="row">{window.minutes === 15 ? "15m" : "1h"}</th>
            {#each window.history as sample, index}
              <td class:current={index === 3} class:missing={ready(sample.turnover) === null} title={sampleTitle(sample)}>
                <time datetime={sample.endAt}>{rankingTimestamp(Date.parse(sample.endAt)).slice(-5)}</time>
                <span>{label(sample.turnover, "turnover", $preferences.turnoverNotation === "compact")}</span>
              </td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>
    <div class="baseline">
      {#each windows as window}
        <p><b>{window.minutes === 15 ? "15m" : "1h"}</b> 普段の中央値 <strong>{label(window.baselineTurnover, "turnover", $preferences.turnoverNotation === "compact")} USDT</strong> · 採用 {window.baselineDays}/7日</p>
      {/each}
      <details>
        <summary>比較基準・採用日時</summary>
        <p>普段比＝現在区間の売買代金÷過去7日の同時刻区間の中央値。欠測日を除き3日以上で算出。前区間比＝直前の同じ長さの区間からの増減率。価格は区間始点から終点の約定価格騰落率です。</p>
        <p>分母が0なら比較基準なし。少額の分母（15mは1,000 USDT未満、1hは4,000 USDT未満）では比率を表示しません。売買代金の増加は買い方向を示しません。</p>
        {#each windows as window}
          <p><b>{window.minutes === 15 ? "15m" : "1h"} 採用区間の終点 JST</b><br />{window.baselineEndTimes.length ? window.baselineEndTimes.map((stamp) => rankingTimestamp(Date.parse(stamp))).join(" / ") : "採用できる履歴なし"}</p>
        {/each}
      </details>
    </div>
  {/if}
</section>

<style>
  .native-activity-details { min-width: 0; margin-bottom: var(--space-sm); padding-block: var(--space-sm); border-block: 1px solid var(--line); color: var(--text); font-size: var(--type-body-sm-size); font-variant-numeric: tabular-nums; }
  h3 { display: flex; align-items: baseline; flex-wrap: wrap; gap: var(--space-xs) var(--space-lg); margin: 0; font-size: var(--type-body-sm-size); }
  h3 span, .source { color: var(--muted); font-size: var(--type-label-caps-size); font-weight: 500; }
  p { margin: var(--space-xs) 0; line-height: 1.35; overflow-wrap: anywhere; }
  table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: inherit; }
  caption { padding-block: var(--space-sm) var(--space-xs); color: var(--subtle); text-align: left; font-size: var(--type-label-caps-size); }
  .period-column { width: 12%; }.turnover-column { width: 25%; }
  th, td { border-bottom: 1px solid var(--line); padding: var(--space-xs) 2px; text-align: right; vertical-align: middle; overflow-wrap: anywhere; white-space: normal; }
  th { color: var(--subtle); font-weight: 500; }th:first-child { text-align: left; }
  .up { color: var(--up); }.down { color: var(--down); }.surge { color: var(--activity); }.missing, .unavailable { color: var(--muted); }
  .cutoffs { color: var(--muted); font-size: var(--type-label-caps-size); }
  b { font-weight: 600; color: var(--subtle); }
  .history time { display: block; color: var(--muted); font-size: var(--type-label-caps-size); }
  .history .current { font-weight: 700; }
  .baseline { padding-top: var(--space-sm); color: var(--subtle); }.baseline strong { font-weight: 600; color: var(--text); }
  details { padding-top: var(--space-xs); color: var(--muted); }
  summary { display: list-item; align-content: center; min-height: var(--control-height-dense); cursor: pointer; color: var(--subtle); }
  summary:focus-visible { outline: var(--focus-ring-width) solid var(--focus); outline-offset: var(--focus-ring-offset); }
  @media (max-width: 960px), (pointer: coarse) { summary { min-height: var(--control-height-touch); } }
</style>
