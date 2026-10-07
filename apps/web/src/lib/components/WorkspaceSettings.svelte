<script lang="ts">
  import { onMount } from "svelte";
  import { getDefaultPreferences, preferences, setPreferences, type WorkspacePreferences } from "$lib/theme/workspace-preferences";
  import { readUserWorkspace } from "$lib/market/user-workspace";
  import type { SavedView } from "$lib/server/user-workspace-repository";
  import { displayNumber } from "$lib/market/number-display";

  let views = $state<SavedView[]>([]);
  let viewError = $state<string | null>(null);
  let message = $state<string | null>(null);
  onMount(() => { void readUserWorkspace().then(value => views = value.savedViews)
    .catch(() => viewError = "保存した表示を読み込めません。ほかの設定は変更できます。"); });

  function update<K extends keyof WorkspacePreferences>(key: K, value: WorkspacePreferences[K]) {
    message = setPreferences({ [key]: value }) ? null : "保存できないため、再読込するまでこのタブ内だけに適用しています";
  }
  function select(key: keyof WorkspacePreferences, event: Event) {
    const value = (event.currentTarget as HTMLSelectElement).value;
    update(key, key.endsWith("Decimals") ? Number(value) : value as WorkspacePreferences[typeof key]);
  }
  function threshold(key: "surgeRatio" | "directionPct", event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    if (!input.reportValidity()) return;
    update(key, Number(input.value));
  }
  function reset(keys: (keyof WorkspacePreferences)[]) {
    const defaults = getDefaultPreferences();
    const patch = Object.fromEntries(keys.map(key => [key, defaults[key]]));
    message = setPreferences(patch) ? null : "保存できないため、再読込するまでこのタブ内だけに適用しています";
  }
  const digits = [0, 1, 2, 3, 4, 5, 6];
</script>

{#if message}<p role="status" class="warning">{message}</p>{/if}
<section aria-labelledby="layout-settings-title">
  <h2 id="layout-settings-title">レイアウトと文字</h2>
  <p>超高密度は行・操作部・パネルの余白をまとめて詰めます。配色とフォントはそのまま使えます。</p>
  <div class="grid">
    <label>レイアウト<select aria-label="レイアウト" value={$preferences.layout} onchange={event => select("layout", event)}>
      <option value="normal">ノーマル</option><option value="ultra">超高密度</option>
    </select></label>
    <label>文字サイズ<select aria-label="文字サイズ" value={$preferences.textSize} onchange={event => select("textSize", event)}>
      <option value="auto">レイアウトに合わせる</option><option value="small">小（11〜12px）</option>
      <option value="standard">標準（12〜14px）</option><option value="large">大（14〜16px）</option>
    </select></label>
    <label>一覧の行間<select aria-label="一覧の行間" value={$preferences.rowSpacing} onchange={event => select("rowSpacing", event)}>
      <option value="auto">レイアウトに合わせる</option><option value="compact">コンパクト</option>
      <option value="standard">標準</option><option value="comfortable">ゆったり</option>
    </select></label>
  </div>
  <p>ノーマルは従来の超高密度です。新しい超高密度では上部操作と一覧をさらに詰め、スマホの操作高さも24px以上に縮めます。文字サイズ・行間を個別に選ぶと、レイアウトの既定値より優先します。</p>
  <p>初期値はスマホで超高密度、PCでノーマルです。保存済みの選択を優先します。</p>
  <button onclick={() => reset(["layout", "textSize", "rowSpacing"])}>レイアウトと文字を初期値に戻す</button>
</section>

<section aria-labelledby="number-settings-title">
  <h2 id="number-settings-title">数値の表示</h2>
  <div class="grid">
    {#each [["percentDecimals", "騰落率・Fundingの小数桁"], ["ratioDecimals", "比率の小数桁"], ["quantityDecimals", "数量の小数桁"]] as [key, label]}
      <label>{label}<select aria-label={label} value={$preferences[key as "percentDecimals" | "ratioDecimals" | "quantityDecimals"]}
        onchange={event => select(key as keyof WorkspacePreferences, event)}>
        {#each digits as digit}<option value={digit}>{digit}桁</option>{/each}
      </select></label>
    {/each}
    <label>一覧の売買代金<select aria-label="一覧の売買代金" value={$preferences.turnoverNotation} onchange={event => select("turnoverNotation", event)}>
      <option value="compact">省略表示（K・M・B）</option><option value="full">全桁表示</option>
    </select></label>
  </div>
  <p>価格は丸めません。計算・順位・絞り込みの値も変えません。売買代金の詳細は常に全桁表示です。微小な非ゼロ値は「&lt;0.01」などで区別します。</p>
  <p class="preview">表示例：騰落率 {displayNumber(1.234567, $preferences.percentDecimals, false, true)}% · 比率 {displayNumber(3.456789, $preferences.ratioDecimals)}倍 · 数量 {displayNumber(1234.56789, $preferences.quantityDecimals)}</p>
  <button onclick={() => reset(["percentDecimals", "ratioDecimals", "quantityDecimals", "turnoverNotation"])}>数値表示を初期値に戻す</button>
</section>

<section aria-labelledby="startup-settings-title">
  <h2 id="startup-settings-title">起動時の表示</h2>
  <p>アドレスに表示条件がない場合の初期値です。共有リンク・一覧への復帰・画面上で選んだ条件を優先します。</p>
  <div class="grid">
    <label>最初に開く画面<select aria-label="最初に開く画面" value={$preferences.initialPage} onchange={event => select("initialPage", event)}>
      <option value="reference">ランキング</option><option value="native">取引所別</option>
    </select></label>
    <label>ランキングの初期比較期間<select aria-label="ランキングの初期比較期間" value={$preferences.initialPeriod} onchange={event => select("initialPeriod", event)} disabled={Boolean($preferences.referenceViewId)}>
      <option value="default">画面の既定値</option><option value="15m">15分</option><option value="1h">1時間</option><option value="24h">直近24時間</option><option value="daily">JST基準時刻から</option>
    </select></label>
    <label>ランキングの初期並び順<select aria-label="ランキングの初期並び順" value={$preferences.initialOrder} onchange={event => select("initialOrder", event)} disabled={Boolean($preferences.referenceViewId)}>
      <option value="default">画面の既定値</option><option value="gainers">上昇率順</option><option value="losers">下落率順</option><option value="turnover">売買代金順</option>
    </select></label>
    <label>ランキングの初期表示列<select aria-label="ランキングの初期表示列" value={$preferences.initialColumns} onchange={event => select("initialColumns", event)} disabled={Boolean($preferences.referenceViewId)}>
      <option value="standard">標準</option><option value="movement">値動き</option>
    </select></label>
    {#each [["referenceViewId", "reference", "ランキングで最初に使う保存表示"], ["nativeViewId", "native", "取引所別で最初に使う保存表示"]] as [key, mode, label]}
      <label>{label}<select aria-label={label} value={$preferences[key as "referenceViewId" | "nativeViewId"]} onchange={event => select(key as keyof WorkspacePreferences, event)}>
        <option value="">使わない</option>
        {#each views.filter(view => view.view.mode === mode) as view}<option value={view.id}>{view.name}</option>{/each}
        {#if $preferences[key as "referenceViewId" | "nativeViewId"] && !views.some(view => view.id === $preferences[key as "referenceViewId" | "nativeViewId"] && view.view.mode === mode)}
          <option value={$preferences[key as "referenceViewId" | "nativeViewId"]}>保存表示を確認できません</option>
        {/if}
      </select></label>
    {/each}
  </div>
  {#if viewError}<p class="warning">{viewError}</p>{/if}
  <p>表示条件は一覧の「表示条件を保存／管理」で作成します。保存表示を選ぶとその条件を使います。削除済みの場合は初期値に戻し、一覧に案内を表示します。</p>
  <button onclick={() => reset(["initialPage", "initialPeriod", "initialOrder", "initialColumns", "referenceViewId", "nativeViewId"])}>起動時の表示を初期値に戻す</button>
</section>

<section aria-labelledby="signal-settings-title">
  <h2 id="signal-settings-title">売買代金と方向の強調表示</h2>
  <div class="grid">
    <label>売買代金の急増倍率<input aria-label="売買代金の急増倍率" type="number" min="1" max="1000" step="any" required value={$preferences.surgeRatio} onchange={event => threshold("surgeRatio", event)} /></label>
    <label>上昇・下落の境界（%）<input aria-label="上昇・下落の境界（%）" type="number" min="0.01" max="100" step="any" required value={$preferences.directionPct} onchange={event => threshold("directionPct", event)} /></label>
  </div>
  <p>昨日・一昨日の両方に対して{$preferences.surgeRatio}倍以上を強調します。価格変化が+{$preferences.directionPct}%以上は上昇、−{$preferences.directionPct}%以下は下落、その間は横ばいです。未取得は横ばいに含めません。</p>
  <p>この設定は強調表示の条件です。ランキングの計算や取得データは変わりません。欠損・更新停止の警告は常に表示します。</p>
  <button onclick={() => reset(["surgeRatio", "directionPct"])}>強調表示を初期値に戻す</button>
</section>

<section aria-labelledby="chart-settings-title">
  <h2 id="chart-settings-title">チャートの初期表示</h2>
  <div class="grid">
    <label>チャートの初期時間足<select aria-label="チャートの初期時間足" value={$preferences.chartInterval} onchange={event => select("chartInterval", event)}>
      <option value="last">ランキングは前回の足・取引所別は15分</option>
      <option value="5">5分</option><option value="15">15分</option><option value="60">1時間</option><option value="240">4時間</option><option value="D">日足</option>
    </select></label>
    <label class="check"><input type="checkbox" checked={$preferences.chartVolume} onchange={event => update("chartVolume", event.currentTarget.checked)} />取引所別チャートの出来高を表示</label>
  </div>
  <p>時間足はランキングと取引所別に適用します。ランキングのTradingViewチャート内の表示項目は、チャート側で操作します。</p>
  <button onclick={() => reset(["chartInterval", "chartVolume"])}>チャートを初期値に戻す</button>
</section>

<style>
  section { padding: var(--space-xl); border: 1px solid var(--line-strong); background: var(--panel); margin-bottom: var(--space-lg); border-radius: var(--radius-sm); }
  h2 { margin: 0 0 var(--space-lg); font-size: var(--type-heading-md-size); }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-lg); }
  label { display: flex; flex-direction: column; gap: var(--space-sm); min-width: 0; font-size: var(--type-body-sm-size); color: var(--subtle); }
  select, input, button { box-sizing: border-box; min-width: 0; min-height: 44px; padding: var(--space-sm); border: 1px solid var(--line-strong); background: var(--surface); color: var(--text); font: inherit; font-size: var(--type-body-sm-size); }
  select { width: 100%; }button { margin-top: var(--space-md); cursor: pointer; }
  .check { flex-direction: row; align-items: center; }.check input { min-height: auto; }
  p { margin: var(--space-sm) 0 var(--space-md); font-size: var(--type-body-sm-size); color: var(--muted); line-height: 1.6; }
  .warning { color: var(--warning); }.preview { font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  @media (max-width: 48rem) { .grid { grid-template-columns: minmax(0, 1fr); }section { padding: var(--space-lg); } }
</style>
