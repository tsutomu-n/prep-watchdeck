# Color and Font Settings Implementation Plan

- 作成: `2026-08-11T13:43:00+09:00`
- 更新: `2026-08-11T18:01:04+09:00`
- 状態: `実装計画`
- チェックポイントID: `CP-01` - `CP-13`
- ブランチ: `ai/add-color-schemes-20260811-1343`
- 破壊的変更: なし

## 目的

現行配色を既定の標準テーマとして維持し、Carbon Aurora、Forest Amber、Plum Signalと、
Paper Ledger、Arctic Terminal、Sage Field、Lilac Currentを
DashboardとSymbol Pageから選択できるようにする。選択はbrowser-localに保存し、chartを含む
全semantic surfaceへ即時反映する。Light 4案は可読性と目への優しさを両立する。
selectorは閉じた状態で現在の`DARK` / `LIGHT`種別を示し、展開時は種別ごとにthemeをまとめる。
さらに全画面共通のfontを「標準」「等幅」から明示選択できるようにする。

## 現状と制約

- runtime color tokenは`watchdeck-theme.css`に一組だけある。
- DashboardとSymbol Pageは同じroot tokenを使うが、共通の配色controlはない。
- MarketChartはmount時にtokenを一度だけ読み、後からの配色変更へ追従しない。
- API、schema、DB、scanner、runtime state、dependencyは変更しない。
- fontは追加downloadを行わず、Windows / Linuxのlocal fontとgeneric fallbackだけを使う。
- 既存のshell script 5件のmode差分は変更・stage対象にしない。

## 実装方針

1. `watchdeck`をfallbackとする8 IDの型、表示順、storage key、DOM属性、変更eventを一つのbrowser moduleへ集約する。
2. 初回描画前に保存済みの有効IDを`html[data-color-scheme]`へ反映する。
3. 同一のsemantic roleを持つ7 alternate paletteをCSSへ追加し、共通のnative selectを両headerへ配置する。
4. theme変更eventで既存chart/seriesへpaletteを再適用し、chart生成、request、observerを増やさない。
5. `DESIGN.md`へpaletteの視覚契約、`docs/current/ui-workflow.md`へ挙動契約を記録する。
6. Light 4案へ`color-scheme: light`を設定し、OS連動なしの明示選択として復元・chart再配色を検証する。
7. theme contractへ種別を持たせ、selectorへ文字による現在種別とnative `optgroup`を追加する。
8. font ID、保存key、DOM属性、変更eventをbrowser moduleへ集約し、初回描画前に復元する。
9. `--font-sans`を2つのlocal-first stackへ切り替え、両headerへ共通font selectorを配置する。
10. font変更時は既存chartへfont familyだけを再適用し、chart生成、request、observerを増やさない。
11. `readable` ID、CSS stack、選択肢、test fixture、文書契約を削除し、旧保存値は既定fontへ戻す。
12. 現在価格を価格専用の可変小数桁で表示し、低価格銘柄を`0`へ丸めない。価格は
    `data-md`の階層へ揃え、Hot staleの文字表示、quality-risk色、row高、Hot ticker更新境界を維持する。
13. Mobile Candidateの上昇・下落tabへ方向色と上辺markerを付け、選択中のfocus色とも併存させる。
    row品質の`判定不能`は維持し、同じrowで活動phaseも`判定不能`になる場合だけ重複表示を省略する。

## テスト方針と完了条件

- unitでID、fallback、保存例外、必須token、contrast、chart palette適用を確認する。
- E2Eで両routeの選択、reload/navigation保持、不正値fallback、chart lifecycle/request不変、responsive targetを確認する。
- E2Eで現在種別の表示、Dark / Lightのgroup名、各groupのtheme数を確認する。
- fontの選択、reload/navigation保持、不正値fallback、chart lifecycle/request不変、responsive targetを確認する。
- unitで高価格と1未満の価格精度、欠損fallbackを確認し、実画面で現在価格が判別可能か確認する。
- 390pxで上昇・下落tabのsemantic color、選択marker、keyboard tab contractを確認する。
- unitとlive DOMで、異常品質labelを残したまま活動phaseの重複`判定不能`だけが消えることを確認する。
- `bun run check`、`bun test`、`bun run build`、関連Playwright、DesignMD lint、`bash scripts/verify-local.sh`、`git diff --check`を通す。
- Desktop/Mobileの8テーマでmovement、warning、quality、focus、欠損状態の識別とoverflow不在を目視確認する。

## 失敗条件・影響範囲・ロールバック

- 現行palette値、データ契約、URL、Dashboard設定、Past Note、chart APIへ変更が必要なら停止する。
- 影響範囲はWebの配色・font token、2 header、MarketChart、Dashboardの現在価格表示、関連docs/testsに限定する。
- ロールバックは追加theme/font module/component/testとalternate CSS blocksを外し、header/chartの接続点を戻す。

## 代替案と未解決事項

- 共通上部barとfixed controlは密度またはoverlay riskが高いため採用しない。
- server-side preferenceと別tab即時同期はscope外とする。
- 未解決事項なし。

## 検証記録

- theme contract / contrast: `29 passed`
- chart appearance unit: `7 passed`
- font contract unit: `5 passed`
- Web unit全体: `223 passed`
- 関連Playwright: color `4 passed`、font `4 passed`、全Playwright E2E: `68 passed`
- `bun run check`: 0 errors / 0 warnings
- `bun run build`: PASS
- DesignMD lint: 0 errors / 0 warnings
- `bash scripts/verify-local.sh`: PASS
  - repository maintenance: 82 passed
  - scanner-core: 249 passed、既存の一時directory cleanup warning 9件
  - Web unit、typecheck、build、全Playwright E2E: PASS
- visual: 8 theme x 2 route x Desktop/Mobileの32画面を確認し、overflow、重なり、情報欠落なし
- selector classification: `DARK` / `LIGHT`表示、2 native group、各4 themeをE2Eと実画面で確認
- font visual: 2 font x 2 route x Desktop/Mobileの8画面を確認し、overflow、重なり、情報欠落なし
- `git diff --check`: PASS
- current price: adaptive precision unit `5 passed`、320px stale price regression `1 passed`、
  標準/等幅のlive価格切れ`0件`、live横overflow `0px`
- mobile movement / unknown labels: 390px semantic tab color・marker・roving E2E `1 passed`、
  live先頭20行の品質`判定不能`保持20件、活動phaseとの重複`6 -> 0`、full gate PASS
