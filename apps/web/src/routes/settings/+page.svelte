<script lang="ts">
  import DailyReferenceSetting from "$lib/components/DailyReferenceSetting.svelte";
  import FontSelector from "$lib/components/FontSelector.svelte";
  import ThemeSelector from "$lib/components/ThemeSelector.svelte";
  import TurnoverDisplaySetting from "$lib/components/TurnoverDisplaySetting.svelte";
</script>

<svelte:head>
  <title>設定 · Prep Watchdeck</title>
  <meta name="description" content="フォント、配色、売買代金の表示小数桁、騰落率の日本時間の基準時刻を設定します。" />
</svelte:head>

<main class="settings-page">
  <header>
    <p class="eyebrow">PREP WATCHDECK</p>
    <h1>設定</h1>
    <p>見やすい表示と、普段使う騰落率の基準を選びます。変更はその場で反映されます。</p>
  </header>

  <section aria-labelledby="display-title">
    <div class="section-heading">
      <h2 id="display-title">表示</h2>
      <p>ランキングと取引所別の画面に共通で適用します。</p>
    </div>
    <div class="display-controls">
      <div class="setting-control"><FontSelector /></div>
      <div class="setting-control"><ThemeSelector /></div>
    </div>
  </section>

  <section aria-labelledby="turnover-title">
    <div class="section-heading"><h2 id="turnover-title">売買代金の表示</h2></div>
    <TurnoverDisplaySetting />
  </section>

  <section aria-labelledby="reference-title">
    <div class="section-heading">
      <h2 id="reference-title">騰落率の計算</h2>
      <p>ランキングの「JST基準時刻から」と、取引所別の約定騰落率に使う基準です。</p>
    </div>
    <div class="reference-control"><DailyReferenceSetting /></div>
    <p class="setting-help">直近の指定時刻からの変化を比較します。市場画面にも適用中の基準時刻を表示します。</p>
    <dl class="time-meanings">
      <div><dt>表示時刻</dt><dd>日本時間（JST / UTC+9）で表示します。</dd></div>
      <div><dt>騰落率の基準</dt><dd>ここで選んだ時刻を使います。「15分」「1時間」「直近24時間」などの比較期間は変更しません。</dd></div>
      <div><dt>日足の区切り</dt><dd>取引所の日足はJST 09:00が区切りです。この設定では変わりません。</dd></div>
      <div><dt>JST当日の高安位置</dt><dd>JST 00:00からの高安を使います。騰落率の基準時刻とは別の指標です。</dd></div>
    </dl>
  </section>

  <aside class="storage-help" aria-label="設定の保存先">
    <h2>このブラウザーに保存</h2>
    <p>設定はブラウザーごとに保存します。PCとスマホでは、それぞれ見やすい表示を選べます。別の端末やブラウザーには同期しません。</p>
  </aside>
</main>

<style>
  .settings-page { max-width: 58rem; margin: 0 auto; padding: var(--space-xl) var(--space-page) calc(var(--space-xl) * 2); }
  header { margin-bottom: var(--space-xl); }
  .eyebrow { color: var(--muted); font-size: var(--type-label-caps-size); letter-spacing: .08em; }
  h1 { margin: var(--space-sm) 0 var(--space-md); font-size: var(--type-title-lg-size); line-height: var(--type-title-lg-leading); }
  h2 { margin: 0; font-size: var(--type-heading-md-size); line-height: var(--type-heading-md-leading); }
  p { margin: var(--space-sm) 0 0; color: var(--muted); line-height: 1.65; }
  section { min-width: 0; padding: var(--space-xl); border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: var(--panel); margin-bottom: var(--space-lg); }
  .section-heading { margin-bottom: var(--space-lg); }
  .display-controls { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-lg); }
  .setting-control { min-width: 0; padding: var(--space-md); background: var(--surface); border: 1px solid var(--line); }
  .setting-control :global(label) { display: flex; flex-direction: column; align-items: stretch; gap: var(--space-sm); font-size: var(--type-body-sm-size); }
  .setting-control :global(select) { width: 100%; min-width: 0; min-height: var(--control-height-touch); }
  .reference-control { max-width: 27rem; }
  .reference-control :global(label) { justify-content: space-between; font-size: var(--type-body-sm-size); }
  .reference-control :global(input) { min-height: var(--control-height-touch); }
  .setting-help { font-size: var(--type-body-sm-size); }
  .time-meanings { display: grid; gap: var(--space-md); margin: var(--space-xl) 0 0; padding-top: var(--space-lg); border-top: 1px solid var(--line); }
  .time-meanings > div { display: grid; grid-template-columns: 10rem minmax(0, 1fr); gap: var(--space-md); }
  dt { font-weight: 700; color: var(--subtle); }
  dd { margin: 0; color: var(--muted); line-height: 1.6; }
  .storage-help { padding: var(--space-md) var(--space-xl); }
  .storage-help h2 { font-size: var(--type-body-md-size); }
  .storage-help p { font-size: var(--type-body-sm-size); }
  @media (max-width: 48rem) {
    .settings-page { padding-top: var(--space-lg); }
    section { padding: var(--space-lg); }
    .display-controls { grid-template-columns: 1fr; gap: var(--space-md); }
    .time-meanings > div { grid-template-columns: 1fr; gap: var(--space-xs); }
    .storage-help { padding: var(--space-md) var(--space-lg); }
  }
</style>
