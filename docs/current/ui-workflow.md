# prep-watchdeck 現行UIワークフロー

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-10T20:04:38+09:00`
- 検証: `2026-08-10T20:04:38+09:00`
- 文書更新作業: `2026-08-10_20:04`（Asia/Tokyo）
- 状態: `現行`

---

## この文書が固定するもの

この文書は、Dashboardと個別Symbol画面の現行操作契約を固定する。market値、件数、
process状態の正本ではない。これらは実画面、state file、service状態で確認する。

情報量の多さは意図したものである。Desktopの密度を保ち、Mobileでは表現とscroll境界を
変えるが、signal、stale、missing、partial、low-quality、ranking item、watchlist row、
銘柄annotationを都合よく省略しない。

## 利用者の基本フロー

1. Topbarのsource、snapshot時刻、service、data qualityを確認する。
2. Candidateのtimeframeとrankingを確認する。ranking itemは個別分析への明示的なlinkである。
3. Watchlistのカテゴリ、view、Raw Sortを使って確認対象を絞る。
4. Watchlist rowを選択し、同じDashboard内のSelected detailを更新する。
5. Selected detailで分類、理由、risk、24h range、VPI補助情報、Past Noteを確認する。
6. より深く確認する時だけ、Selected detailの「個別分析を開く」linkからSymbol画面へ進む。
7. Symbol画面のMonitoring Rail、chart、時間軸別データ、市場条件を確認する。
8. 後日の監視に必要な時だけ、Past Noteを60日有効の銘柄annotationとして保存する。

## shared themeとsemantic color

全routeは`apps/web/src/routes/+layout.svelte`から
`apps/web/src/lib/styles/watchdeck-theme.css`を読み込む。色、文字、余白、row、control、focus、
chart tokenのruntime正本はこのshared themeだけである。productionのroute/component styleにある
raw hexadecimalおよび`rgb()` / `rgba()`色literalは0件で、componentはsemantic tokenか、そのtokenを
入力にした`color-mix()`だけを使う。raw値はshared themeとcolor adapterのtest fixtureに限定する。

semantic colorの役割は次で固定する。

- `up` / `down`: 価格変化、変化率、sparkline、candle、方向付きvolumeなど、市場方向だけ。
- `warning` / `warningBorder`: 運用上の注意、risk確認、draft衝突、計画外結果、
  service劣化。価格の正負やvalidation errorには使わない。
- `qualityGood`: 検証済み品質、完了したcheck、正常なsystem state。
- `qualityRisk`: stale、missing、partial、low-confidence、unreadable、取得失敗、入力validationなど、
  実データまたはfieldの問題。通常の注意喚起には使わない。
- source、service、runtimeのsystem stateは`qualityGood`、`warning`、`qualityRisk`を状態に応じて使い、
  marketの`up` / `down`とは色値も意味も分離する。

幅`560px`以下のTopbarはsource、service、runtime boundaryを横並びの3 cellへ圧縮する。
sourceとserviceの主要状態は`role="status"`、`aria-live="polite"`、`aria-atomic="true"`を維持し、
runtime boundaryも省略しない。

## Dashboardの構造とフォーカス順

### 固定されたsection順

Topbarの後にあるworkspaceのDOM順は、breakpointにかかわらず次で固定する。

1. Candidate (`data-dashboard-section="candidate"`)
2. Watchlist (`data-dashboard-section="watchlist"`)
3. Selected detail (`data-dashboard-section="detail"`)
4. 補正順位 (`data-dashboard-section="smart-rank"`)

通常の`Tab`移動も、このsource order内で各sectionの操作要素を順に通る。Desktopの
`85rem`以上ではSelected detailを右列へ置くが、CSS gridによる見た目の配置だけを変え、
DOM、読み上げ順、keyboard順を入れ替えない。正の`tabindex`による順序の上書きもしない。

Watchlist row群は後述のroving tab stopにより1つだけがTab順へ入り、そのrowから`Tab`で
Selected detailの個別分析linkへ進める。補正順位はdetailの後に続く。

### row選択と個別分析navigationの分離

Watchlist row全体は`button[data-row-select]`であり、navigation linkではない。

- click、`Enter`、`Space`はrowを選択し、URLを変えずにSelected detailを更新する。
- 選択状態はrowの見た目だけでなく`aria-pressed="true"`でも示す。
- focusを別rowへ動かしただけでは選択symbolを変えない。
- 個別分析への遷移はSelected detail内の明示的なlinkだけが行う。実pathは
  `/symbols/<symbol>?tf=<selectedTimeframe>`で、accessible nameは
  「`<symbol> の個別分析を開く`」である。
- Candidateのranking itemは最初からnavigationを目的とした`a.rank-row`であり、
  Watchlistの選択buttonと混同しない。

filterやview変更で選択symbolが一時的に非表示になっても、別symbolへ自動選択しない。
Selected detailは「選択銘柄を保持中」を表示し、入力中の下書きを保持する。対象が再表示
されるまでは保存不可であることも隠さず表示する。

### VPI-Lite+ 実験表示

Cold snapshotに有効な`summary.vpiLitePlus`がある時だけ、Selected detail内へ実験表示を置く。
Dashboardの概要panelはBenchmark / Targetのstateとdata qualityだけを表示し、scoreを出さない。
選択rowに一致する`row.display.vpiLitePlus`がある時だけ、選択銘柄の補助詳細としてscore、
reason、risk、funding、open interest、data timestampを表示する。常に「実験中の補助指標で、
売買シグナルではない」と明記する。

VPIはWatchlist row、ranking、sort、Candidate順へ入れない。Hot ticker deltaは価格DOMだけを
更新し、Cold VPI表示を再計算しない。top-levelまたはitemが不正ならVPI部分だけを非表示にし、
既存Dashboardを継続表示する。これはVPIの低品質状態を隠す処理ではなく、consumer契約を満たさない
任意payloadをfail-closedで拒否する境界である。

### Watchlist rowのroving keyboard

Watchlist row群のTab stopは常に1つだけである。

- 現在focus中のrowがまだ表示中なら、そのrowを`tabindex="0"`にする。
- そうでなければ、表示中の選択rowを`tabindex="0"`にする。
- 選択rowも表示されていなければ、先頭rowを`tabindex="0"`にする。
- それ以外のrowは`tabindex="-1"`にする。
- `ArrowDown` / `ArrowUp`は次／前の表示rowへfocusだけを移す。端では停止する。
- `Home` / `End`は先頭／末尾の表示rowへfocusだけを移す。
- key移動後のrowは、bounded scroll領域の外なら領域内へscrollする。
- `Enter` / `Space`で初めてfocus rowを選択する。
- row群からfocusが外れた後もTab stopは1つを維持し、選択状態は失わない。

keyboard helpは「上下キーで銘柄を移動、EnterまたはSpaceで選択」としてrow groupへ
`aria-describedby`で関連付ける。

## signal、stale、品質の提示契約

### movement signal

`movementSignals`が返したsignalは、Desktop/Mobileとも全件をrow内へ表示する。
「先頭だけ」「+N」「hover時だけ」の省略はしない。現行signalは次を含む。

- 5分/1時間一致（短縮表示: `一致`）
- 短期逆行（`逆行`）または直近失速（`失速`）
- 5分急変（`急変`）
- 出来高増（`量増`）

各chipは短縮labelを視覚表示し、`aria-label`には完全なlabelを持つ。さらにrow選択buttonの
`aria-label`へ、分類、表示label、選択時間軸の変化と代金、15m量倍率、品質、注記、
全signalの完全labelを連結する。色だけでsignalを区別しない。

### Hot価格のstale

Hot ticker価格が5秒を超えて更新されていない時は、価格をquality-risk色にし、同じ価格欄へ
`STALE`を文字で表示する。row選択buttonの`aria-describedby`は価格欄の`id`を参照するため、
読み上げでも価格値と`STALE`を取得できる。stale化によってrow高を変えたり、他のfieldを
隠したりしない。

snapshotの`STALE`、rowの`PARTIAL`などもsource banner、品質欄、日本語label
（例: 「古いデータ」「一部不足」）で視覚表示し、rowのaccessible nameへ品質labelを含める。
Hot ticker updateは対象symbolの現在価格DOMだけを更新し、ranking順、Watchlist順、選択、
filter、入力中の下書きを変えない。

## touch targetと操作状態

`DESIGN.md`とshared themeが次を固定する。

- Desktopの高密度controlは`34px`高を使用できる。
- `48rem`以下、またはcoarse pointerでは、link、button、text input、select、textarea、
  summaryを原則`44px × 44px`以上にする。
- checkbox/radio本体はnative sizeを維持し、関連labelを`44px × 44px`以上のtargetにする。
- primary mobile actionを指定する場合は`48px`高を使う。
- action labelは1行を維持し、control group側をwrapまたはstackする。
- keyboard focusは`focus` tokenの`2px`ringと`2px`offsetで視覚表示する。
- hover styleはhover可能なfine pointerだけへ適用する。
- hover、focus、active、selected、disabled、loadingでborder幅、padding、control寸法を変えない。
- disabled controlは理由を表示し、loading controlは`aria-busy`と進行中labelを持つ。
- validation errorはquality-riskの視覚状態、`aria-invalid`、関連error、`role="alert"`で示す。
- 保存成功は`role="status"`と`aria-live="polite"`で通知する。

DashboardとSymbol画面ではPast Note保存の処理中stateをrouteが所有する。同じ保存の再実行は
完了まで無効化し、送信元symbol以外へsuccess/errorを波及させない。Dashboard view設定の保存も
view単位の処理中stateを持つ。`finally`で処理中stateを解除し、失敗時は既存入力を維持する。

`320px`、`375px`、`414px`、`768px`と、幅`1200px`のcoarse pointerをE2E対象に含める。

## Desktop / Mobileの情報密度

Desktopは高密度な主分析surface、Mobileは短い確認、候補review、現在symbolのcontext確認に
使う。MobileへDesktop tableの列配置は押し込まないが、item自体は削らない。

幅`960px`以下では次のbounded scrollを使う。

- Candidateのmobile ranking body: `min(48svh, 28rem)`を上限に縦scrollする。
- Watchlistのrow領域: `min(60svh, 36rem)`を上限に縦scrollする。
- 両方とも`touch-action: pan-y`、`overscroll-behavior-y: auto`を使う。
- ranking linkと表示対象rowは全件DOMに残し、各領域内で末尾まで到達可能にする。
- Candidateは`561px`以上で連続した4列、`560px`以下で4つのautomatic activation tabにする。Desktop/Mobile表現は両方SSRし、CSS breakpointで切り替える。ArrowLeft/ArrowRightは循環し、Home/Endを含めてfocus移動とpanel切替を同時に行う。
- ranking linkの整形済みsymbol名は省略しない。rank列と値列を縮退させ、`320px`でも
  `1000000BABYDOGE`級のsymbol列がellipsisや1文字だけにならず、必要なら途中でwrapする。
- 変化rankingの見出しはsignの断定ではなくsort契約を表す`上昇順` / `下落順`とする。
  各値の色は所属panelではなく実数値の符号で決め、正は`up`、負は`down`、0はneutralにする。
- view、category、保存済みview設定を切り替えた時は、Watchlist row領域を先頭へ戻す。

400 rowと4 ranking panel × 10 itemを使うstress E2Eでも、末尾itemへscrollでき、Selected
detailが無制限に下へ押し流されないことを確認する。この件数はruntime固定値ではなく、
情報を削らずbounded scrollを保つための検証fixtureである。

Watchlist rowは広いtable表現で`42px`、compact card表現で`82px`を基準にする。signal、
注記、選択、focus、STALEの有無で同じ表示モード内のrow高を変えない。

`320px`ではDashboard CandidateとSymbol chart上部にある6つのtimeframe controlを、
3列×2行へ均等配置する。Symbolの時間軸別データboardはMobileで2列×3行を維持する。

## 個別Symbol画面の順序

Symbol画面はchart-firstで、top-level DOM順を次に固定する。

1. Symbol header: 一覧へ戻るlink、symbol、score、分類、品質、選択時間軸変化
2. 分析領域
   1. 主チャート: timeframe navigationの後に価格・出来高chart
   2. Monitoring Rail: 分類、label、品質、選択時間軸、ranking位置、movement signal、risk tag
3. 時間軸別データ: 6 timeframeの変化、代金、volume ratio
4. 補助情報workspace

補助情報workspace内の順序は次で固定する。

1. 24h レンジ
2. 74h 条件
3. 品質と市場条件
4. 理由とリスク
5. 銘柄注記
6. スナップショット

Desktopでは最初の4 sectionを2列、以降を全幅で表示する。Mobileでは同じDOM順の1列へ
stackする。見た目は1つの外枠とdividerで階層化し、各sectionを独立card catalogへ戻さない。
Mobileでも内容を非表示にせず、root横overflowを発生させない。

幅`720px`以下では、Symbol header直後に`個別分析内を移動`というsticky local navigationを
表示する。chart、監視材料、時間軸、市場条件、銘柄注記の5 anchorを横scrollで全件到達可能にする。
anchor activation後は対象sectionへfocusを移し、次の
`Tab`がsection内の最初の操作へ進む。long-form workspace末尾には`分析上部へ戻る`linkを置き、
page先頭へfocusを戻す。DesktopではこのMobile補助navigationを表示せず、chart-firstのDOM順は
変えない。

## Chartのsingle-container契約

Symbolのchartは、初期時点でembedded candleもAPI candleも0件でも、1つの
`.chart-surface`をmountする。

- chart library、chart instance、candlestick、volume、line seriesをmount時に1回だけ作る。
- APIは選択symbol、timeframe、snapshot `runId`を指定して取得する。
- symbol、timeframe、runIdが変わった時は前requestをabortし、新しいrequestへ切り替える。
- API candleが遅れて到着した時は、同じchart instanceのseries dataを更新する。
- 遅延到着のためにcontainer、chart instance、library chunkを作り直さない。
- abort済みrequestのresponseまたはerrorは、現在のseriesやempty stateを書き換えない。
- 表示可能なcandleもline dataもない間はcontainer上へ「ローソク足データなし」をoverlay表示する。
- candle到着後はoverlayを外し、同じcontainerへcanvasを表示する。
- theme tokenが欠損または不正ならtoken名を含むerrorとしてfail closedし、silent fallbackしない。
- componentがmodule load完了前にunmountされた場合はchartを作らない。作成済みなら
  `ResizeObserver`をdisconnectし、chart instanceをremoveし、active bars requestをabortする。

chartのcanvas surfaceは`aria-hidden="true"`とし、chart regionをscreen reader向け要約へ
`aria-describedby`で関連付ける。要約は`aria-live="polite"`で次を伝える。

- candle: symbol、timeframe、本数、UTCの開始／終了、最新足の始値・高値・安値・終値・出来高
- line-only: symbol、timeframe、点数、UTCの開始／終了、最新値
- empty: 「表示できる価格データはありません」
- load error: 視覚表示と`role="alert"`

存在しないOHLCVをline-only／empty状態から捏造しない。API barsの遅延到着後は同じ要約を
更新し、E2Eでは1 request、1 chunk、1 chart creationのままOHLCV要約へ変わることを確認する。

## 保存mutationと下書きの整合

非同期保存はrouteがsingle-flight stateを所有し、button local stateだけに任せない。

### Dashboard

- Past Noteは1つのroute-owned保存lockを持ち、request開始時のorigin symbolと入力revisionを
  固定する。同じ保存の再実行は完了まで拒否する。
- response時に同じsymbol、同じrevisionなら送信済み入力だけをclearする。保存中に入力が変わった
  場合は新しい入力を保持し、送信時点の内容だけが保存されたことを通知する。
- success/errorはorigin symbolへだけ表示し、別symbolのSelected detailへ漏らさない。
- Dashboard view設定はview単位のsaving stateを持ち、保存中のviewだけを無効化する。

### 個別Symbol画面

- Past Noteは1つのactive tokenにorigin symbolとsubmitted revisionを持つ。同一symbolの新しい入力は
  保持し、API payloadはclick時点の内容から変えない。同じrevisionなら入力をclearする。
- success/errorはsymbol別に保持する。保存中に別Symbolへclient navigationしても、
  移動先のdraftやfeedbackを変更せず、元Symbolへ戻った時だけ結果を表示する。

すべてのmutationは`finally`でlockを解除する。処理中buttonは`aria-busy`と操作別labelを持ち、
保存結果はpolite status、失敗はalertで伝える。

## 非目標となった取引ワークフロー

Attack Ticket、Trade Memo、TRADE / SKIP記録、Weekly Review、Deal Check、Pre-Trade Check、
Position Size PressureはDashboardとSymbol画面へ表示しない。これらの入力、計算、保存、編集、
削除、CSV exportをUIから復元しない。Past Noteはこの代替ではなく、期限付き銘柄annotationである。

## 表示の意味と禁止事項

- rankingとscoreは確認順であり、売買推奨ではない。
- focus colorは選択timeframe、選択symbol、現在のattention、primary actionに限る。
- up/downは市場方向、warningは注意、quality colorはデータ品質に使い分ける。
- 高score、上昇色、ranking位置を「買うべき」という表現にしない。
- stale、missing、partial、low-quality dataを非表示にしない。
- 内部categoryの`NO_TRADE`は変更せず、利用者向け表示だけを`監視除外候補`とする。
- 自動注文、自動売買、buy/sell recommendationを示すUIを追加しない。

## 実装と検証の根拠

| 契約 | 現行実装 | 主な検証 |
| --- | --- | --- |
| Dashboard DOM順 | `apps/web/src/routes/+page.svelte` | `apps/web/tests/e2e/responsive-layout.e2e.ts` |
| row選択、roving keyboard | `apps/web/src/lib/components/dashboard/DashboardWatchlist.svelte`, `apps/web/src/lib/components/dashboard/DashboardMarketRow.svelte`, `apps/web/src/lib/components/dashboard/SelectedSymbolOverview.svelte` | `apps/web/tests/e2e/home.e2e.ts` |
| 全signal、STALE、row高 | `apps/web/src/lib/components/dashboard/DashboardMarketRow.svelte`, `apps/web/src/lib/market/row-analysis.ts` | `apps/web/tests/e2e/responsive-layout.e2e.ts`, `apps/web/tests/e2e/home.e2e.ts` |
| Mobile bounded all-item scroll | `apps/web/src/lib/components/dashboard/DashboardRankingArea.svelte`, `apps/web/src/lib/components/dashboard/DashboardWatchlist.svelte` | `apps/web/tests/e2e/responsive-layout.e2e.ts` |
| Symbol DOM順、Monitoring Rail、flat workspace | `apps/web/src/routes/symbols/[symbol]/+page.svelte`, `apps/web/src/lib/components/symbol/SymbolMonitoringRail.svelte` | `apps/web/tests/e2e/symbol-workspace.e2e.ts`, `apps/web/tests/e2e/monitoring-symbol.e2e.ts`, `apps/web/tests/e2e/responsive-layout.e2e.ts` |
| chart instance、late bars、要約 | `apps/web/src/lib/MarketChart.svelte`, `apps/web/src/lib/market/chart-data.ts`, `apps/web/src/lib/market/chart-theme.ts` | `apps/web/tests/e2e/realtime-dashboard.e2e.ts`, `apps/web/src/lib/market/chart-data.test.ts`, `apps/web/src/lib/market/chart-theme.test.ts` |
| Past Note mutation、symbol scope、revision保持 | `apps/web/src/routes/+page.svelte`, `apps/web/src/routes/symbols/[symbol]/+page.svelte`, `apps/web/src/lib/past-note/` | `apps/web/src/lib/past-note/*.test.ts`, `apps/web/tests/e2e/home.e2e.ts`, `apps/web/tests/e2e/symbol-workspace.e2e.ts` |
| 監視専用production境界 | `apps/web/src/routes/`, `apps/web/src/lib/`, `scripts/maintenance/monitoring-only-boundary.test.mjs` | `apps/web/tests/e2e/retired-routes.e2e.ts`, `scripts/maintenance/monitoring-only-boundary.test.mjs` |
| shared theme、色、密度、compact status、誤推奨防止 | `DESIGN.md`, `apps/web/src/routes/+layout.svelte`, `apps/web/src/lib/styles/watchdeck-theme.css` | `apps/web/tests/e2e/responsive-layout.e2e.ts` |
| VPI-Lite+実験表示、optional payload、Hot非影響 | `apps/web/src/lib/market/vpi-lite-plus.ts`, `apps/web/src/lib/components/dashboard/DashboardVpiExperimentPanel.svelte`, `apps/web/src/lib/components/dashboard/SelectedSymbolVpiDetail.svelte` | `apps/web/src/lib/market/vpi-lite-plus.test.ts`, `apps/web/tests/e2e/home.e2e.ts`, `apps/web/tests/e2e/realtime-dashboard.e2e.ts` |

UI変更時は`DESIGN.md`を先に読み、Dashboard、Symbol page、Desktop、Mobileのどこへ
影響するかを明示する。変更後は対象に近いunit/E2Eに加え、`bun run check`、`bun test`、
`bun run build`を実行する。情報を減らす変更は、Mobile対応や簡素化という理由だけでは認めない。

## Candidate条件とOI表示

Candidate見出し下はsnapshot summaryをvalidationし、74h価格AND売買代金条件と
`合致 / 未一致 / 判定不能`件数を表示する。不正または欠損summaryでは数値を推測せず、
条件metadataを取得できないこととsnapshot更新後の再確認を案内する。旧snapshotのランキングが
現行74h gate済みであるとは断定しない。

Symbol Monitoring Railは`OI 60分`を`増加 / 横ばい / 減少 / 不明`で表示する。
74h条件の複合結果は`一致 / 未一致 / 判定不能`で表示する。VPI-Lite+のOI availabilityは
別契約なので維持し、重複していた非VPIのraw open interest表示だけを置かない。

`summary.volumeRatio15m`をvalidationできた場合だけ、`15m量倍率`へ
`約24hの15m中央値比`のような基準説明を付ける。値は有限時に`3.4×`、欠損時に`—`とする。
metadataが不正・欠損ならsample数や期間を推測せず、基準詳細を取得できないfallbackを表示する。
Symbol時間軸boardでは15mだけ量倍率行を生成し、他timeframeではDOMを生成しない。
