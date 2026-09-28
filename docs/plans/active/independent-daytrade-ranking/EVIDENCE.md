# 独立デイトレランキングの進捗・証拠

- 作成: `2026-09-12T07:46:31+09:00`
- 更新: `2026-09-12T10:33:12+09:00`
- 状態: `実装計画`

## 全体判定

**BLOCKED。G01の全件照合に要確認44行が残り、許可範囲の追加調査でも必要な一次根拠を得られなかった。ゴールは完了していない。**
CP1〜CP4のsource実装、確認済み529参照契約の隔離した実Provider受入、ケース別の実Widget表示、
既存機能を含むローカル検証は実施済み。未確認を未対応へ変更せず、要求・採用範囲を縮めていない。
本書は [/home/tn/projects/prep-watchdeck/docs/plans/active/independent-daytrade-ranking/GOAL.md](/home/tn/projects/prep-watchdeck/docs/plans/active/independent-daytrade-ranking/GOAL.md) の完了条件に対する実績である。

作業branchはai/independent-daytrade-ranking-20260912-0736。
開始時と現在のHEADは8d12fa6979700f3ed281f06262a91cb25faa635c。
開始時の未commit 33ファイルを保全した。commit、push、PR、本番deploy、既存unit・live DB操作は未実施。
試験用collector、Browser、Web previewは終了し、試験stateと証拠を残した。

## 監査後の追加差分

09:58のsource監査後、REST同時実行・cooldown、map/Widgetの検証、未対応表示、全体gateなどに
追加変更を検出した。この継続作業ではそのsource変更を行っておらず、検出時の内容を保全した。
10:04時点の8ファイルに検証scriptの変更が加わった後、関連検証と全529契約の実受入を再実行した。

最新のRanking Coreは91 pytest PASS、Ruff/Pyrefly/schema検証もPASS。
Web関連8 unit、check/build、関連E2E 10件は追加変更後にPASSし、その後のWeb source変更はない。
最新検証時の43ファイルのhashは10:33 JSTの再確認でも一致した。

実受入は10:13:59開始時のsourceで実行し、通常・75秒停止後の復旧とも3周期で全529契約を確認した。
受入中に4ファイル（実装2、tests 2）が変わったため、実行sourceと最新sourceが同一だったとは扱わない。
実装差分はcatalogの不正形式の拒否と、verified行のWidget未対応理由・根拠の必須化だけである。
最新unitと公開catalogの再取得でこの差分を検証し、529参照契約のrevision変更0、現在mapへの影響0を確認した。
最終source差分・実受入・最新checkの対応は
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-source-delta.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-source-delta.json)、
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json)。

差分と保全先は
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/post-audit-changes.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/post-audit-changes.json)。
G01の追加確認・PONSの不足条件の訂正は
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/g01-continuation-review.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/g01-continuation-review.json)。
要確認44行は維持し、未対応や対応済みへの変更は行っていない。

## G01〜G10の監査

| ID | 判定 | 確認した範囲と証拠 |
| --- | --- | --- |
| G01 | BLOCKED | 元1,203契約の漏れ・重複なし。529参照とWidgetを照合。44行は一次根拠不足で未確定。[/home/tn/projects/prep-watchdeck/apps/ranking-core/data/qualification-evidence.json](/home/tn/projects/prep-watchdeck/apps/ranking-core/data/qualification-evidence.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/g01-continuation-review.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/g01-continuation-review.json)。 |
| G02 | PASS | 独立SQLite、元stateと重なる保存先・symlink拒否、DB依存なし。元stateを空のread-only mountで隠して収集を継続。専用state外のcanary書込み拒否を実測。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/write-guard-evidence.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/write-guard-evidence.json)、[/home/tn/projects/prep-watchdeck/apps/ranking-core/tests/test_storage.py](/home/tn/projects/prep-watchdeck/apps/ranking-core/tests/test_storage.py)。 |
| G03 | PASS | 確定終値・同期間売買代金、欠測・実0、JST境界、世代固定、契約revisionをunitで検証。実Bybit ETH・Binance 牛来の全3期間を独立Decimal計算と照合。[/home/tn/projects/prep-watchdeck/apps/ranking-core/tests/test_ranking.py](/home/tn/projects/prep-watchdeck/apps/ranking-core/tests/test_ranking.py)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/adopted-live-value-comparison.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/adopted-live-value-comparison.json)。 |
| G04 | PASS | 確認済み全529契約を同じTで毎分発行。追加差分後も通常3周期、WS再接続、停止後復旧3周期、12読取り条件で外部REST増加なし。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6/acceptance.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6/acceptance.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-source-delta.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-source-delta.json)。 |
| G05 | PASS | 期間・方向・下限・任意JST設定・保存失敗・空順位・欠測表示をWeb unit/E2Eで確認。[/home/tn/projects/prep-watchdeck/apps/web/tests/e2e/ranking.e2e.ts](/home/tn/projects/prep-watchdeck/apps/web/tests/e2e/ranking.e2e.ts)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-ranking-e2e.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-ranking-e2e.log)。 |
| G06 | PASS | 529件の参照/Widget metadata整合と、通常・倍率・中国語・crypto indexの実描画を確認。選択ID維持、旧要求排除、mapから消えた選択の停止も確認。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-ranking-e2e.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-ranking-e2e.log)。 |
| G07 | PASS | Desktop/Mobile E2Eと実画像を確認。検索・比較toolbarを隠し、キー入力・親URLでAAPLへ切り替わらない実挙動を確認。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-mobile-million-mog.png](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-mobile-million-mog.png)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-desktop-light-index.png](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-desktop-light-index.png)。 |
| G08 | PASS | 元のnative Chart/騰落率作業を保全。既存4 artifact・Market Coreに今回の変更なし。既存を含む全回帰がPASS。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/baseline-preservation-check.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/baseline-preservation-check.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local-correct-runner.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local-correct-runner.log)。 |
| G09 | PASS | 529実参照契約を別process・専用state・別port・OS書込み制限下で観測。通常、実WS切断、75秒停止、再開時の欠測と全件復旧を記録。[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6/acceptance.jsonl](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6/acceptance.jsonl)。 |
| G10 | PASS | 現行docs、起動/停止/復旧、map更新、残件と再開条件を記録。metadata/link/diff検証と最終source照合がPASS。[/home/tn/projects/prep-watchdeck/docs/current/operations.md](/home/tn/projects/prep-watchdeck/docs/current/operations.md)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json)。 |

G04/G06/G09のPASSは確認済み529契約に対する実装・実データ検証の判定であり、未確認44行を含む
G01の完了を意味しない。実Widgetは全metadata整合と代表ケースの実描画を組み合わせて確認した。
全529契約を一つずつ実描画したとは扱わない。

## checkpoint

| checkpoint | 現在地 | 残作業 |
| --- | --- | --- |
| CP0 | BLOCKED。元差分・実効state・全名簿・公開API・配信予算を確認。参照範囲をversion付きmapへ保存。 | 44行のidentity・数量倍率・別名・未対応根拠を確定する。 |
| CP1 | PASS。Python独立workspace、SQLite、map/snapshot/schema、loopback API、書込み境界。 | G01確定によるmap更新以外の必須実装なし。 |
| CP2 | PASS。確定足WS、初期/復旧REST、bounded queue、保存・再接続・契約検証。 | 同上。 |
| CP3 | PASS。同じTと固定入力による3期間計算、下限・順位、32件cache。 | 同上。 |
| CP4 | PASS。必須操作、保存、選択保持、単一Widget、Desktop/Mobile。 | 同上。 |
| CP5 | BLOCKED。実Provider/Widget受入・回帰・docs整備まで実施。 | G01の解消後、変更mapの全件受入と全体監査を完了する。 |

## 対象名簿と採用範囲

| 項目 | 実績 |
| --- | --- |
| map version | 9250aeccad8d3836e3cd8646 |
| 対応確認時刻 | 2026-09-12T09:16:01.096+09:00 |
| 元名簿のsnapshot時刻 | 2026-09-12T07:40:00.800+09:00 |
| 元契約 | 1,203件。Aster 559、Bitget 466、Hyperliquid Core 178。全IDとversionを保持。 |
| 統合後 | 694行。crypto候補573行、crypto以外の対象外121行。 |
| 参照API対応 | 529行。Bybit 478、Binance 51。固定USDT linear perpetual。 |
| Widget対応 / 両方対応 | ともに529行。通常Widget検索metadataで契約を別途照合。 |
| 要確認 | 44行。数値とWidgetを生成しない。 |
| 未対応として確定済み | 0行。別名未照合36行を未対応へ付け替えていない。 |

source側の名簿・対応表・根拠は
[/home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-roster.json](/home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-roster.json)、
[/home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-map.json](/home/tn/projects/prep-watchdeck/apps/ranking-core/data/initial-map.json)、
[/home/tn/projects/prep-watchdeck/apps/ranking-core/data/qualification-evidence.json](/home/tn/projects/prep-watchdeck/apps/ranking-core/data/qualification-evidence.json)。
名簿fingerprintは6483590f64384715c9d8d7d3ef8c6bf4b1aebd3d88dd6d218802931fb0af1763。
初回の候補数470/478等は調査途中の値であり、最終529の受入と混同しない。

照合には元/参照Providerの公式catalog、公式指数構成の原資産と明示係数、通常Widgetの資産metadata、
公式の数量説明を用いた。価格・指数値は元の3取引所からランキングへ取り込んでいない。
Bitgetの指数構成名には独自aliasがあるため、同じspotPair文字列だけで別資産へ統合しない。
Aster MEME/PROSは同名peerから分離し、確認できない契約を既存のverified行へ混ぜなかった。
BybitのPURRは株式Hyperliquid Strategiesの分類であり、Hyperliquid Coreのcrypto PURRへ結び付けていない。

### 残る44行と再開条件

| 理由 | 行数 | 対象・必要な根拠 |
| --- | --- | --- |
| no_exact_reference_alias_review | 36 | AI, AIW3, ANSEM, ASTEROID, AVL, B-MONEY, BASECAT, BAY, BEN, BGB, BONER, BREW, BUILD, CARDS, CATE, DELTA, FLORK, FONE, FUN, LAPTOP, MAX, MEMESTOCK, PAIR, PENGUIN, PI, PUNDIAI, PURR, RTX, SHROOM, STONK, STONKBROKER, STONKS, TROLL, UNITAS, UP, ZCAT。元資産の正規ID・公式別名と採用catalogの全件照合により、対応または参照契約不在を確定する。 |
| quantity_multiplier_unverified | 5 | CAT、CHEEMS、NEX、RATS、kNEIRO。Bitgetの4契約の数量倍率、およびHyperliquid kNEIROの経済的同一性を明示する一次根拠が必要。 |
| original_identity_conflict | 2 | Aster MEMEUSDT / PROSUSDT。同名のMemeland / Pharos等との同一性を確定できない。元資産の正規IDが必要。 |
| identity_evidence_missing | 1 | Hyperliquid PONS。公式Core catalogへの掲載は確認済み。他取引所と同一の原資産であることを示す独立した根拠が不足する。 |

公式catalog、指数構成、Bitgetの公開契約情報、通常のAster/Bitget画面、Widget metadataを調べたが、
上記を確定できる情報は得られなかった。CHEEMSのproject/addressが合っても1MCHEEMSの数量倍率を
symbol prefixや価格比だけで決めない。試した追加確認は
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/additional-original-identity-evidence.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/additional-original-identity-evidence.json)、
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/bitget-cheems-identity.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/bitget-cheems-identity.json)、
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/aster-identity-conflicts.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/aster-identity-conflicts.json) に残す。

最小の再開条件は、これらの原資産ID・数量倍率・公式別名の一次資料を得ること。
資料により参照契約不在を確定できた行だけを理由付きunsupportedへ変更する。
PONSの名前一致だけで同一資産と確定せず、既存collectorやlive DBをこの作業で書き換えない。
map更新後は全original ID・revision・Widget bindingの照合と、変更された採用範囲の実受入を行う。
未確認のまま全対応とする仕様変更、外部Providerの大幅追加、有料sourceは今回の承認範囲ではない。

## 実Providerの有限受入

CP0では候補531契約（Bybit 474 / Binance 57）について180秒の公開WS観測を行い、
全候補で3周期の確定1分足を受信した。Bybit到着遅延p50 677ms / p99 1,142ms、
Binance p50 1,454ms / p99 3,025ms。これを根拠に発行猶予8秒、処理deadline 12秒を採用した。
これはidentity採用の証拠とは別である。
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/bybit-stream-probe.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/bybit-stream-probe.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/binance-stream-probe.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/binance-stream-probe.json)。

09:28 JSTまでの最終map受入は上限900秒、実測657.89秒。専用stateは
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/runtime-qualified](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/runtime-qualified)、loopback API portは18769。
実効元state /home/tn/.local/share/prep-watchdeck-market を
試験processのmount namespaceで空のread-only領域へ隠し、DB環境変数を渡さず実行した。

- 通常: 09:18 / 09:19 / 09:20 JSTの3世代で、15分・1時間・JST 00:00基準の全て529/529。
- 実WS切断: 両Providerの2socketを閉じ、両方のreconnectを2秒後に観測。
- 収集停止: 75秒停止後に同じSQLiteとmapで再開。履歴不足の有効数161→284→384→493を隠さず表示。
- 復旧: 09:26 / 09:27 / 09:28 JSTの3世代で全3期間529/529。
- 読取り分離: 通常・再開後それぞれ12条件を同じgenerationへ問い合わせ、外部REST数は前後同一。
  通常Bybit 65 / Binance 39、再開後Bybit 479 / Binance 52。
- 最大generation処理708ms、最大RSS 295,684KiB（約288.8MiB）。接続はProviderごと1。

最終受入の初期stateには先行試験の履歴がある。51追加参照はRESTで初期化した。
最終529全件を空SQLiteからcold startした証拠とはしない。75秒停止後の全件欠測補完と復旧は実測した。
同hostの本番負荷との長期共存、systemd templateのMemoryMax/CPUQuota適用は未検証であり、本番反映に含めない。

追加差分後の受入は10:13:59〜10:28:09 JST、上限900秒以内の約850秒で終了0。
専用stateは [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/acceptance-current-cexdkna6)、API portは34655。
先行する専用SQLiteをread-onlyで複製した別stateを使い、元stateを空のread-only mountへ隠した。

- 通常: 10:18 / 10:19 / 10:20 JSTの3世代で、全3期間529/529。
- 実WS切断から2.001秒で両Providerの再接続を観測し、その後75.059秒停止した。
- 復旧: 欠測中の有効数178→284→385→489を表示し、10:26 / 10:27 / 10:28 JSTに全3期間529/529。
- 通常と復旧後の各12読取り条件で、REST数は前後ともBybit 479 / Binance 52。
- 最大generation処理468ms、最大RSS 288,260KiB（約281.5MiB）。終了後はport閉鎖を確認した。

この受入も空のSQLiteからの全件cold startではない。実行sourceと途中の入力検証差分は前節の証拠で区別する。

計算照合はBybit ETHUSDTとBinance 牛来USDTについて、同じTの実RESTと独立したDecimal計算を用いた。
6比較全てPASS、最大差は騰落率約1.95e-14 percentage points、売買代金0.0000082 USDT。
検証後のProvider訂正や全銘柄の全履歴一致を保証するものではない。

### 初期失敗と修正

初回の復旧試験ではREST補完queueの開始境界が処理待ち中に進み、必要な古い足が残った。
queue投入時に最初の欠測境界を固定する修正と回帰testを追加し、最終529の受入を通した。
初回ログ [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/runtime-qualified/acceptance.jsonl](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/runtime-qualified/acceptance.jsonl) を残し、成功ログで上書きしていない。

## Webと実Widget

実表示は [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-widget-acceptance.json) に7ケースを記録した。
BTC、1000PEPE、1000000MOG、Binance 牛来/NIULAI、BTCDOMについて、実際の価格とローソク足を確認した。
Desktop 1440px、Mobile 390px、dark/lightの実画像を確認済み。未確認CATではWidgetが0件で理由を表示した。
[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-unverified-quantity.png](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/actual-ranking-unverified-quantity.png)。

親URLにtvwidgetsymbol=NASDAQ:AAPLを指定しても選択済みBTCを保持した。
検索・比較buttonを隠し、AAPLのキー入力でsymbol dialogが開かず、無関係な契約へ移動しないことを確認。
右クリック/メニュー操作でも対象外symbolへの導線は観測しなかった。
アプリ操作の期間変更では同じ実frameを保持した。毎分更新後のframe・選択・足保持は制御clockのE2Eで検証した。
これは将来のTradingView仕様変更や全内部UIを網羅した制御保証ではない。

Widgetの内部操作で変えた足・日付範囲はアプリ設定へ同期しない。アプリの「チャートの足」が保存対象で、
明示的な再読込み・銘柄/テーマ/アプリ足変更時は再生成される。毎分の順位更新では再生成しない。
実Widget表示中の既存Market/selection/chart-history/price-change API呼出しは0、UI errorは0。

## 自動検証・回帰・境界

| 確認 | 結果 | 証拠 |
| --- | --- | --- |
| 先行Repo全体 | 終了0。Market Core 78 pytest、Ranking Core 46 pytest、Web 156 unit、E2E 32。専用一時Postgresは動的loopback port32769で起動し終了時に除去。現行の全件照合gate追加前の結果。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local-correct-runner.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local-correct-runner.log) |
| 最新Ranking Core | 追加差分後91 pytest PASS、Ruff/Pyrefly 0 errors、関連20 file format PASS。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-latest-pytest.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-latest-pytest.log)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-checks.json) |
| 最新Web | 関連8 unit PASS、check 0 errors/0 warnings、build PASS、関連E2E10 PASS。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-web-build.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-web-build.log)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-ranking-e2e.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/continuation-ranking-e2e.log) |
| map/schema | 構造と保存済み証拠はPASS。require-reviewed gateは要確認44により終了1。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-map-evidence-check.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-map-evidence-check.json)、[/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-checks.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-checks.json) |
| DESIGN | 0 errors / 0 warnings。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-checks.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/final-checks.json) |
| 元差分の保全 | 開始33fileのうち24fileはbyte一致、9fileは今回の許可範囲を追記。欠落0、stage0。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/baseline-preservation-check.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/baseline-preservation-check.json) |
| OS書込み制限 | 専用state内canary成功、外canaryはEROFS、host canary不変。元stateは見えない。 | [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/write-guard-evidence.json](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/write-guard-evidence.json) |

初回の全体検証はWebでbun testを直接使い、Vitest用vi.waitForが使えず停止した（終了143）。
[/home/tn/projects/prep-watchdeck/scripts/verify-local.sh](/home/tn/projects/prep-watchdeck/scripts/verify-local.sh) をpackage scriptのbun run testへ修正し、全体検証を再実行してPASS。
初回ログは [/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local.log](/home/tn/projects/prep-watchdeck/var/tmp/ranking/cp0-x3fqnezx/verify-local.log) に保持。初期Mobile横幅超過、Ruff整形、docs metadataの
失敗も修正後に対応するcheckを通した。失敗を成功数へ含めていない。
全体検証後に追加したmap根拠検証と5件のmap unitはfocused検証で確認した。無変更で全suiteを反復していない。

追加差分の検証途中には、catalogのtestsと実装が更新中のrunで17 failed / 74 passed、Ruff 3 errorsを観測した。
入力検証と整形の変更がそろった後、91 pytest、Ruff、Pyreflyを再実行してPASS。
現在の全体gateはrequire-reviewedを含み、要確認44行・Widget要確認44行により終了1となる。
この既知のG01未達のため全体gateは再実行せず、変更範囲の検証と実受入を行った。現行全体gateをPASSとは記録しない。

## 起動・停止・引継ぎ

実行手順は [/home/tn/projects/prep-watchdeck/docs/current/operations.md](/home/tn/projects/prep-watchdeck/docs/current/operations.md)、対応表更新は
[/home/tn/projects/prep-watchdeck/apps/ranking-core/data/README.md](/home/tn/projects/prep-watchdeck/apps/ranking-core/data/README.md)。通常起動は書込み制限wrapperを使い、
専用map/state/portを指定する。停止後も証拠と履歴を保持し、同じ契約revisionだけを再利用する。
元の収集・Postgres・4 artifact・選択・Past Noteに今回の書込みを追加していない。

本番へ反映する場合は、未達G01を解消したうえで、実効pathを設定した専用unitとWebの反映を別途扱う。
この作業ではunitのinstall/enable/start/restart、deploy、migration、commit/pushを実行しない。
要確認が残るためactive planを削除せず、全条件を満たした後に現行仕様・判断へ引き継いで閉じる。
