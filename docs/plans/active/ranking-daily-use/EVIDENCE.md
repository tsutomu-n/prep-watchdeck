# デイトレランキング日常利用の証拠

- 作成: `2026-09-12T21:19:09+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 状態: `実装計画`

## 開始点

開始当時、利用者の明示承認によりD01〜D04のnative Goalを登録し、D05と稼働操作は対象外とした。
その後の包括承認で、ランキング完成・D05に必要な作業は承認済みになった。中断時点の正本は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/RESUME.md](RESUME.md)。以下の日時付き結果は観測当時のsource/mapに対する証拠である。
作業先は/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700、branchはai/ranking-daily-use-20260912-2119、
開始HEADは8d12fa6979700f3ed281f06262a91cb25faa635c。
既存267 source filesを/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/baseline-source.tar.gzへ保全し、
/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/baseline-manifest.jsonにSHA256を記録した。
開始diff/indexと元checkoutの状態も同directoryへ保存。指定worktreeをCWDとする他processは観測されなかった。

## 旧基準でのチェックポイント（改訂前）

| 項目 | 状態 | 確認・残作業 |
| --- | --- | --- |
| D01 | BLOCKED | S09まで逐次反映。元1,203契約/691行、対応531・未対応36・要確認3・対象外121。最終mapの全件gate/受入は未達。 |
| D02 | PASS | 固定した直前1世代、同条件順位差、明示状態、計算/表示回帰、実世代比較を確認。 |
| D03 | PASS | 定義どおりの計算と欠測表示、既存順位維持、実API独立9比較、Desktop/Mobileの表示一致を確認。 |
| D04 | PARTIAL | 空state・保存済みstateの有限復旧・実画面・運用手順を確認。全体はD01とfull gate未達。 |
| D05 | 未実施 | 包括承認済み。D04 PASSと具体的な稼働反映先・差分・切戻し対象の確定待ち。 |

旧証拠は観測当時の証拠であり、変更後sourceの受入には読み替えない。

## D01 再確認 / D02・D03 計算実装

- 全件根拠checkerは終了0、531対応・28未対応・12要確認・121対象外、元1,203契約/692行を再確認。
- `validate-map --require-reviewed`は終了1、12銘柄・12Widget要確認。未達を維持。
- 公開一次API12 URLを取得（すべてHTTP 200）。数量の明示定義と資産identity/CAは解消せず、mapを変更していない。
  証拠: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/d01-primary-refresh.json。
  Bitget上場記事 https://www.bitget.com/support/articles/12560603884273 も原資産名10000NEXの記載で、NEX数量への換算を定義していない。
- D02は直前の発行済み入力を1世代保持し、32条件cache/世代、最大2世代へ制限。再起動時の過去snapshotを比較元として復元しない。
  手計算・後着訂正等27件PASS、ランキング全96件PASS（D03追加前）。Web focused 8件PASS、Svelte 0 errors/0 warnings。
- D03は同じDBの既存high/low列を世代作成時に読取り、指標を固定。schema migration/保存期間/外部取得先の変更なし。
  新しいmetricVersionはtrade-close-quote-turnover-analysis-v2。計算関連40件PASS。
- 初回の型生成は未installのjson2tsで終了127。既存lockのbun install --frozen-lockfile後に生成成功。
  rootからのPyreflyは誤ったproject範囲を選んで失敗。正しいranking-core CWDでは終了0だがGit除外のtests省略を発見し、--use-ignore-files=falseで全指定source/testsを検証する。

このcheckpoint後、以下のUI確認と最終sourceでの有限受入を実施した。

## D02・D03 回帰とD04空state準備

- ランキング全109 pytest、Ruff check/format、明示file指定Pyreflyが終了0。型検査はtestsも含む。
- Web unit158件、check 0 errors/0 warnings、関連E2E12件（Desktop/Mobile各6）がPASS。
  新E2Eは変更前の保全コピーではrank-change表示がなく失敗し、変更後で成功。初回のbaseline実行は
  Svelte alias解決で失敗し、sync後は意図した表示欠落で失敗した。
- UI実画像と対応レスポンスは/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/desktop/ と/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/mobile/ に保全。
- 実WidgetはBTC、1000PEPE、NIULAI（元名は牛来）、BTCDOMをDesktop/Mobileで計8ケース確認。
  実フレームのsymbol解決、足の配信・描画、契約名、エラーなしを照合し、8実画像を確認。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/actual-widget-results.json。全531契約の個別描画とは扱わない。
- 実画面とAPIの追加指標が同じgenerationで一致することもDesktop/Mobileで確認。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/live-display-results.json。
- 独立Decimal計算はETHUSDT（Bybit）、龙虾USDT（Binance）、1000PEPEUSDT（Bybit）の3契約×3期間でPASS。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/live-value-comparison.json に元API、共通T、中央値、高安、誤差を保存。
- 変更前sourceが作ったSQLiteを新sourceで再開し、table SQL不変・平常比/当日位置計算・
  初回順位比較不可を確認。/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/legacy-state-compatibility.json。
- 空stateからの有限準備は終了0、source hash不変。全531契約で3期間の有効数が531の
  3連続世代を確認。15分平常比は530 ready/1 no_baseline、1時間は531 ready、当日位置は531 ready。
  中央値0を有効な2.0倍等へ変換していない。最大RSS 291540 KiB、
  最大世代処理986ms。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/cold-run.json と/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/cold-state/preparation.json。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/isolation-check.json で専用state外の書込み拒否と元stateを隠した状態を確認。
- Repo全体gateは終了1。maintenance104件、Market78件、Ranking109件、schema/根拠整合は通過し、
  要確認12銘柄/12Widgetで停止。/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/full-gate.log。結果をPASSへ読み替えない。

保存済みcold-stateの同一hashコピーを使い、通常3世代・実WS再接続・75秒停止・復旧3世代を
最大900秒の別試験で確認した。/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/recovery-run.json にseed/source/portを記録。

- Web全E2E34件がPASSし、既存Universe ExplorerのChart・選択・表示にも回帰なし。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/full-web-e2e.log。
- Gitのignoreに依存しない明示指定でMarket63 files、Ranking17 filesのPyreflyを確認し、両方終了0。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/explicit-pyrefly-results.json。
- 今回変更は保全時から24 files。既存のChart source・map/data・元checkout status・indexを維持。
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/daily-use-changes.json と/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/daily-use.patchへ差分を保存。


## D04 復旧受入と最終監査（2026-09-12・旧map）

- 保存済みstateの受入は2026-09-12 21:47:41〜22:02:10 JST、約869秒で終了0。
  実行前後のsource hashは一致。/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/recovery-run.json と
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/recovery-state/acceptance.json に記録。
- 通常21:52/21:53/21:54、復旧22:00/22:01/22:02 JSTの各3連続世代で、
  同じT・全531契約・15分/1時間/JST期間の有効数531を確認。
  復旧直後の最初の世代は有効219/履歴不足312で、順位変化は219件とも比較不可。
  次の発行済み世代がそろってから比較し、過去snapshotを新規扱いへ流用しない。
- 実WS 2接続を閉じ、両Providerの再接続を2003msで確認。collector停止は75009ms。
  通常/復旧それぞれ12並列readの前後でRESTはBybit481・Binance52のまま増加なし。
- この復旧試験の最大世代処理985ms、最大RSS466820 KiB（約456 MiB）。
  空state試験と合わせても12秒deadline・150秒鮮度を維持した受入世代を確認。
  手動観測RSSはcgroup制限適用の証拠ではない。実hostの制限適用・稼働受入はD05に残る。
- 15分平常比の1件no_baselineは中央値0のUSD1USDT。全窓が存在するが数値を作れない
  正当な状態として保持。履歴不足をこの状態へ変更して合格させていない。
- 空stateと再開で追加取得は専用のSQLiteだけに保存し、元stateを隠した隔離を維持。
  新指標のための保存形式migration、参照先拡張、取得上限緩和は行っていない。

この表の「最終」は当該2026-09-12試験時点を指す。mapは4ce42c272921615dbf0b64e5。
2026-09-13のmap更新後に実Provider/全件Widget/復旧受入をやり直したという意味ではない。

| 初期版条件 | 当該試験時の状態 | 根拠と限界 |
| --- | --- | --- |
| G01 | BLOCKED | 元1,203契約/692行の保持と構造照合は確認。銘柄/Widget12行の根拠が不足し、全件gate終了1。 |
| G02 | PASS | sourceの分離を維持。隔離外書込み拒否・元state非参照下で全531件の取得継続を実測。 |
| G03 | PASS | 計算fixture、既存境界tests、実API3契約×3期間の独立計算。 |
| G04 | PASS | 最終sourceで共通T・全対応531件・通常/復旧各3世代、再接続、12readerの取得独立。 |
| G05 | PASS | Web158 unit、34 E2Eで並び順・期間・下限・JST設定・状態表示と保存を確認。 |
| G06 | PARTIAL | 対応済み範囲のmap構造整合・選択保持・実Widget8ケースは確認。全件確定はG01の12行に依存。 |
| G07 | PASS | Desktop/MobileのE2E、実API表示一致、実画像、外部URL指定でも選択契約が維持されることを確認。 |
| G08 | PASS | Market78 pytest、既存Web回帰、保全点との差分。既存Chart・4 artifact/schema・mapを変更していない。 |
| G09 | PASS | 空state有限準備と保存済みstate有限復旧の実Provider証拠。fixture受入とは分離。 |
| G10 | PASS | 現行仕様・操作/復旧/切戻し手順、証拠、失敗を含む必須check結果と残作業を記録。 |

G02〜G09のPASSは記録したsource・対応範囲・有限観測に限る。G01未達を補うものではない。
D02/D03はPASS、D04全体とD01〜D04のローカル完成はPARTIAL。
repo必須gateの終了1を維持し、active planは閉じない。文書の状態はnative Goalを変更しない。

## 追加調査前の阻害条件と未実施（履歴）

- Bitget CHEEMS・NEX・RATS: 元instrumentと原資産数量倍率を明示する公式契約仕様。
- Aster PROSUSDT: Pharos/旧Prosperを区別する公式project・chain/contract等のidentity。
- Aster AI・B-MONEY・BEN・BONER・BREW・MAX・MEMESTOCK・PAIR:
  指数式の別名を原資産と採用先契約へ結び付ける公式定義。

既存の一次API・上場記事・公開検索でこれらの定義を確定できなかった。
新しい根拠が得られたら元instrument IDを保ってmapと証拠を同時更新し、
全件照合と変更範囲の回帰・最終mapでの実受入を再実行する。
根拠なしに未対応へ付け替えたり、同じ検索を反復して判定を作ったりしない。

commit/push/PR/merge、元checkoutへの統合、既存unit/live DB操作、D05は未実施。
これは追加承認前の記録である。現在D05は包括承認済みだが、D04 PASSと具体的な反映対象の確定は依然必要。


## 明示許可後の追加調査

公開公式Web、公式画面が利用する公開API、公式告知を調査した。変更はこの証拠文書と調査成果物だけで、
map、qualification、product source、稼働state、unitには反映していない。
上の「追加調査前」の未解決事項のうち、Aster 9行には次の新しい根拠が得られた。
資産identityの確認と、ランキングへの採用・未対応判定・Widget実受入は別段階である。

| 元契約 | 今回確認したこと | 調査後の判断 |
| --- | --- | --- |
| Aster PROSUSDT | 公式画面のDetails APIがPharos、PROS、project URL、Ethereum/Base CAを返す。Bybit PHAROSUSDTの指数にはPROSのspot pairが含まれ、multiplierは1。 | 既存crypto:PHAROSへの統合候補。元instrument IDを保持する。map反映と最終受入は未実施。 |
| Aster AIUSDT | Artificial Inu、Robinhood Chain CA。projectとMEXC AIINU告知が同じCAを示す。 | AIINUを一次根拠のある別名として追加調査に使用。Gensyn AIとは別資産。 |
| Aster B-MONEYUSDT | Aster告知とLBank BMONEY告知のBSC CAが一致。LBankは特殊文字を除いた別名だと説明。 | BMONEYを一次根拠のある別名として追加調査に使用。 |
| Aster BENUSDT | AsterとLBankのBSC CAが一致。 | 元資産の同定を補強。 |
| Aster BONERUSDT | AsterとMEXCのRobinhood Chain CAが一致。 | 元資産の同定を補強。 |
| Aster BREWUSDT | AsterとMEXCのBSC CAが一致。 | 元資産の同定を補強。 |
| Aster MAXUSDT | AsterとprojectのBSC CAが一致。候補GIGGLEはBinance告知のCAが異なる。 | GIGGLEを同資産候補から除外。projectはGiggle Academyとの非提携を明記。 |
| Aster MEMESTOCKUSDT | Aster告知、Details API、projectのBSC CAが一致。 | 元資産の同定を補強。MEMESTは二次情報の検索候補であり確定別名ではない。 |
| Aster PAIRUSDT | AsterとMEXCのRobinhood Chain CAが一致。 | 元資産の同定を補強。 |
| Bitget 1MCHEEMSUSDT | frontendのcoin informationでCheemsとBSC CAを確認。 | Bitget契約1単位の原資産数量の明示定義は未取得。 |
| Bitget 10000NEXUSDT | 公式上場告知とfrontendは契約名を示す。Bybitの指数multiplierはBybit側の定義。 | Bitget側の10,000倍を確定する根拠にはならない。 |
| Bitget 1000RATSUSDT | frontendの契約情報とBybit側のmultiplierを再確認。 | Bitget側の1,000倍を明示する定義は未取得。 |

AsterのDetails APIは公式画面と元契約を結ぶ一次の観測だが、中の説明はCoinMarketCap由来。
Aster独自執筆の契約仕様として扱わず、独立したproject/他取引所のCAと併せて評価した。
AsterのexchangeInfoではPROSUSDTがTRADING/PERPETUAL、別名PHAROSUSDTはPENDING_TRADINGでcontractType空欄。
名称が二つ存在するだけでは別資産と判定できないことを確認した。

採用先の全候補はBybitのTrading/LinearPerpetual/USDT建て・USDT決済519契約、
BinanceのTRADING/PERPETUAL/COIN/USDT建て・USDT決済526契約。
指数構成はBybit 519/519、Binance 526/526で取得できた。Binanceの非ASCII名5件は
最初のURL未encodeにより送信前に失敗し、正しくencodeした5件の取得で解消。失敗記録も保持した。
全候補の指数構成を照会し、確認した別名、検索候補、数量接頭辞を正規化して候補を抽出した。
AI系のAIGENSYNUSDTはMEXCのAI pairを指数に含むが、Binance/MEXC公式のGensyn CAが
Artificial Inuと異なり除外できる。MAXの候補GIGGLEUSDTもCAで除外した。
PROS以外のAster 8行について、確認した別名に一致する採用可能な参照契約は得られなかった。
これは有限のcatalog/既知別名照合であり、未発見の別名や未文書化の指数変換まで不存在を証明していない。
この結果だけで8行をunsupportedへ変更していない。

Bitget frontendのcountMultiplier、priceMultiplierは注文数量・価格刻みの設定であり、
原資産数量の換算倍率に読み替えられない。価格比や1M/10000/1000という名前からも確定していない。
今回の公開Web/画面/API調査で数量定義を取得できなかった事実を残し、同じ調査を無制限に反復しない。

主な一次根拠:

- [Aster PROS Details API](https://www.asterdex.com/bapi/futures/v1/public/composite/market/symbol/detail?symbol=PROS&lang=en)、[Bybit PHAROS指数](https://api.bybit.com/v5/market/index-price-components?indexName=PHAROSUSDT)。
- [Aster AI Details API](https://www.asterdex.com/bapi/futures/v1/public/composite/market/symbol/detail?symbol=AI&lang=en)、[Artificial Inu project](https://artificialinu.com/)、[MEXC AIINU告知](https://www.mexc.com/en-GB/announcements/article/first-in-market-17827791537014)。
- [Aster B-MONEY/MEMESTOCK告知](https://x.com/Aster_DEX/status/2096602459405988223)、[LBank BMONEY告知](https://www.lbank.com/zh-TC/support/articles/2096174677117370368)。
- [Aster BEN/BONER告知](https://x.com/Aster_DEX/status/2096965860405690670)、[Aster BREW告知](https://x.com/Aster_DEX/status/2096821963310481828)、[Aster MAX告知](https://x.com/Aster_DEX/status/2097299961293762999)、[Aster PAIR告知](https://x.com/Aster_DEX/status/2096485089890947216)。
- [Binance GIGGLE告知](https://www.binance.com/en/support/announcement/detail/8272526b66b042dfbfbd7b717f3d4490)、[Binance Gensyn告知](https://www.binance.com/id/support/announcement/detail/71f44e5e014c445697bb6a6f70315e35)。

全12行のchain/CA/一次URL/判断/限界: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/authorized-research/research-summary.json。
採用先全件の別名照合と取得不足: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/authorized-research/adopted-index-alias-audit.json。
原responseとendpoint/bodyの対応: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/authorized-research/direct-manifest.json、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/authorized-research/aster-target-manifest.json。
取得済み公開responseの一覧・SHA256: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/daily-use-20260912-211909/authorized-research/research-artifact-manifest.json。

最初の広いbrowser収集はawait後の連番で一部filenameが衝突したため、探索用途に限定し、
そのbodyをURLに結び付いた証拠として使用していない。後続のtarget/direct専用収集で再取得した。
Detailsのvisible textは保存できたが対象elementのscreenshotは失敗し、画像検証PASSとは扱っていない。

残作業は、PROS候補のmap/証拠への反映と受入、Aster 8行の残る分類判断、
Bitget 3行の元契約数量倍率、最終mapの全件gateと変更で無効になる受入の再実行。
D01の達成およびD01〜D04全体の完成は未確認のまま。今回の調査を完了扱いにしてもGoal完成にはしない。


## S01: PROSを1件ずつの手順で解消

利用者の包括許可と逐次実行の指示に基づき、最初の作業をPROSのみに限定した。
候補作成 → 検証 → 正本反映の順に進め、その他11件の判定は変更していない。

- Asterの公式Details、元契約catalog・指数、Bybitの対象catalog・指数の計5 URLを再取得し、すべてHTTP 200。
  Aster DetailsのPharos/PROS、CMC 39682、Ethereum/Base CA、元契約のTRADING/PERPETUAL、
  Bybit PHAROSUSDTのPharos名とPROS指数multiplier 1を再確認した。
  Asterの独立したPHAROSUSDT行はPENDING_TRADING・contractType空欄であり、対応先に採用していない。
- Aster Detailsは公式画面とPROSを結び付ける観測であり、埋込み説明metadataはCoinMarketCap由来として記録。
  その説明をAster自身が執筆した契約仕様と呼び替えていない。
- review:aster:PROSUSDTを既存crypto:PHAROSへ統合。元aster:PROSUSDT/versionId 1007と
  bitget:PROSUSDT/versionId 448、両元契約の数量倍率1を保持。
  固定参照bybit:PHAROSUSDT:feff280bb71a8df143d3とBYBIT:PHAROSUSDT.Pは従来のまま。
- 変更前後で全1,203 original identityが等しく、Pharos以外の全行と全531参照契約が等しいことを検証。
  表示行は692→691、対応531・未対応28・要確認11・対象外121。Widgetも対応531・要確認11。
  新map versionはdbf8cc641092b21b158953e7。
- 検証済み候補と同じmapを正本へ反映し、qualificationのmapVersion/verifiedAtと未解決台帳を更新。
  verifiedAtは今回のmap検証時刻であり、他銘柄の過去の観測を再取得済みに読み替えていない。
- 候補の全件証拠checkerは終了0。既存のmapping pytestは12 passed。
  `validate-map --require-reviewed`は残る11銘柄・11Widgetにより終了1を維持。
- 現行productのwidgetDocumentを使った隔離iframeで、実TradingView Widgetを1440/390幅で確認。
  両方でBYBIT:PHAROSUSDT.Pのsymbol_resolved、チャートデータ更新、canvas表示を取得し、
  保存画像でPharosのローソク足・価格軸を確認した。外側URLのAAPL指定でもPharosを維持。
  これは対象Widgetの個別受入であり、product routeや新mapの全件collector受入ではない。
- 初回HTML生成はBunのtsconfig overrideでdirectory mismatchの診断が出たため、Webの通常CWDへ変更して
  再生成し、診断なしの出力を使用した。Web取得toolのAPI直接open失敗は公開URLのCLI直接取得で確認した。

候補・変更前の保全・一次response・検証記録: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031。
元契約と対象外差分の比較: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/candidate-audit.json、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/final-audit.json。
Widgetの機械観測: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/widget-results.json。実画像: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/widget-1440.png、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/widget-390.png。
正本反映後の文書/証拠checker・全件gateの終了結果: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pros-qualification-20260913-082031/validation.json。

S01のsource対応と個別Widget確認はPASS。D01全体はBLOCKED、D04全体はPARTIALを維持。
既存のD02/D03・復旧証拠は旧mapの観測として保持し、最終mapの全件受入で必要な確認を再実行する。
次はS02としてAster AIUSDTの1件を扱う。稼働反映・commit/push・外部照会の送信は本checkpointでは行っていない。


## S02: Aster AIを採用範囲内の未対応として確定

- Aster Detailsを再取得し、Artificial Inu、Robinhood Chain CA
  0x2E8c31162b855A2ffa90F6F8634643Ad6F111e18を確認。MEXCの一次告知は同CAをAIINUとする。
- Bybit/Binanceのcatalogを再取得。対象519/526契約と全revisionが前回の全指数照合時から不変であり、
  Bybitの取得cursorは空。AI/AIINUと補助検索名に合う直接の対象契約はない。
  前回取得済みの全対象指数からの候補抽出も再計算し、該当は両ProviderのAIGENSYNUSDTだけ。
- この候補2契約の指数を今回再取得。MEXC等のAI pairを含むが、BybitのfullName、Binance/MEXCの
  Gensyn公式告知と異なるchain/CAで別資産と判定。Binanceの同名AIUSDTはSETTLINGで採用範囲外。
  元指数のAI-USDG・ETH-AIに現れるAIは公式Detailsで資産を同定し、ETH/USDGは換算・quote項として扱う。
  指数式を数値評価してランキングへ流用したり、式の無視による空候補だけを根拠にしていない。
- 元crypto:AIとaster:AIUSDT/versionId 2316を保ち、statusをunsupported、理由を既存の
  no_adopted_reference_after_identity_auditへ変更。固定参照がないためWidgetもunsupportedとする。
  これは確認時点の採用2社の暗号資産USDT linear perpetual範囲の判断であり、他市場・将来上場・
  未文書化identityの不存在を断言しない。参照先拡張や未確認許容への要求変更は行っていない。
- 候補の全件証拠checkerは終了0。他の全行、全1,203 original、全531 referenceは変更なし。
  新mapは7d8ca692eefadb86dd5f56a4、691行、対応531・未対応29・要確認10・対象外121。
  S02はsource分類までPASS。最終mapの全件受入は未達のまま。次はB-MONEYを1件扱う。

全件候補抽出と判定根拠: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008/alias-content-audit.json、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008/decision-audit.json。
一次responseとcatalog同一性: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008/primary-manifest.json、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008/catalog-comparison.json。
正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/ai-qualification-20260913-083008/validation.json。


## S03: B-MONEYを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、BNB Smart ChainのCA 0xF49725118cB0707B8706fFFFe895F3AB16da7777を共有。確認した名称はB-MONEY / BMONEY。
- 一次の照合先: [B-MONEYの資産定義](https://www.lbank.com/zh-TC/support/articles/2096174677117370368)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 055bfde1440baed04ad68ae4。候補の全件証拠checkerは終了0。対応531・未対応30・要確認9・対象外121。Widget要確認も9。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/B-MONEY/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/B-MONEY/validation.json。


## S04: BENを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、BNB Smart ChainのCA 0x7BC70aE0f2A67d2fDc0180a697a611F21c857777を共有。確認した名称はBEN。
- 一次の照合先: [BENの資産定義](https://www.lbank.com/id/support/articles/2096804716414500864)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 4b9ac212937844bbbcedf5c5。候補の全件証拠checkerは終了0。対応531・未対応31・要確認8・対象外121。Widget要確認も8。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BEN/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BEN/validation.json。


## S05: BONERを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、Robinhood ChainのCA 0x98096d17e191B3dA1d5f99a6D7b3584351b11E18を共有。確認した名称はBONER。
- 一次の照合先: [BONERの資産定義](https://www.mexc.com/pt-BR/announcements/article/mexc-moves-boner-to-innovation-zone-17827791538023)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 9109b52353d991da052cd32c。候補の全件証拠checkerは終了0。対応531・未対応32・要確認7・対象外121。Widget要確認も7。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BONER/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BONER/validation.json。


## S06: BREWを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、BNB Smart ChainのCA 0xfa6D9B504848606Eb9aeC04CCc161D169B3f2159を共有。確認した名称はBREW。
- 一次の照合先: [BREWの資産定義](https://www.mexc.com/announcements/article/first-in-market-17827791538296)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 8fe0143e69154130d7fe6b02。候補の全件証拠checkerは終了0。対応531・未対応33・要確認6・対象外121。Widget要確認も6。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BREW/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/BREW/validation.json。


## S07: MAXを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、BNB Smart ChainのCA 0xe9Bc5C6A86caA44fD7b469bf3cc7c563E4F77777を共有。確認した名称はMAX。
- 一次の照合先: [MAXの資産定義](https://www.maxbnb.meme/)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は2件。GIGGLE候補は公式の異なるchain/CAにより除外した。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 468bef6d4f55ecb7cc16ec6d。候補の全件証拠checkerは終了0。対応531・未対応34・要確認5・対象外121。Widget要確認も5。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/MAX/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/MAX/validation.json。


## S08: MEMESTOCKを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、BNB Smart ChainのCA 0x6FF45323817d1d53bbb8A8dFbA9245aE74057777を共有。確認した名称はMEMESTOCK。
- 一次の照合先: [MEMESTOCKの資産定義](https://memestock.run/stock)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 006a56349ab48b5349548df1。候補の全件証拠checkerは終了0。対応531・未対応35・要確認4・対象外121。Widget要確認も4。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/MEMESTOCK/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/MEMESTOCK/validation.json。


## S09: PAIRを1件ずつ照合して反映

- Aster公式上場告知と照合先の一次情報が、Robinhood ChainのCA 0x6b1d42927B1a84eC28Fa88d4fC6FA7AF404966beを共有。確認した名称はPAIR。
- 一次の照合先: [PAIRの資産定義](https://www.mexc.co/en-GB/announcements/article/first-in-market-17827791538269)。Asterの元指数式も今回再取得し、資産identityを式の文字列だけから推定していない。
- S02で確認したBybit 519/Binance 526の全catalogと、同じ契約集合の保存済み全指数から候補を抽出。候補は0件。空の元指数を根拠にしていない。
- 確認時点の採用範囲では未対応と判定。他市場・将来上場・未文書化identityの不存在は断言しない。元ID・全参照・他の全行を保持してこの1行と証拠だけを更新。
- 新map 1ee6cd08e257dc1a90fff0e6。候補の全件証拠checkerは終了0。対応531・未対応36・要確認3・対象外121。Widget要確認も3。
- 根拠と差分条件: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/PAIR/decision-audit.json。正本反映後の確認: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/PAIR/validation.json。


## S10〜S12の準備と逐次反映後の監査

- Bitgetの公式contact-us画面でCustomer serviceを選び、support@bitget.comを確認。
  3契約それぞれの原資産数量、価格の単位、公式仕様URL/API field、適用日を尋ねる文面を作成した。
  利用可能なメール送信用接続と送信元がないため未送信。公開仕様への照会以外の情報を文面へ含めていない。
  agent-browser CLIは未導入のため、既存Playwright/Chromeの新規・未認証contextで受付経路だけを確認し、終了した。
- 数量倍率の未確認3行をそのまま保持。名前・価格比・他取引所の倍率・注文刻みで補完していない。
- S02〜S09の分類をsourceだけでも再監査できるよう、Bybit 519/Binance 526の全参照指数について、
  原response hash・観測時刻・identity fieldsをqualificationのindexComponentsへ保存した。
  価格はこのqualificationへ取り込まず、取得時刻を今回の時刻へ書き換えていない。
- 最後の文書内容照合で、中間のREADME件数に単純な部分文字列置換による誤りを発見し、
  対応表の実集計へ修正。候補map・全件checkerの集計は正しく、説明文だけの誤りだった。
  最終監査では説明文の対応531・未対応36・要確認3と、未対応内訳33+1+1+1をmapと照合する。
- 本turnの変更は対応表、qualification、data guide、既存planと証拠文書だけ。
  元checkout・両Git index・全original identity・全固定参照契約・対象外の行・product実装を保全する。
  sourceのS01〜S09完了と、最終mapの全件実Provider/画面/復旧受入・D05稼働反映は別の状態である。

照会文（未送信）: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/bitget-unit-inquiry.txt。送信先確認と未送信理由: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/bitget-inquiry-status.json。
今回の最終内容監査・差分保全・文書check: /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/final-audit.json、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/aster-classification-sequential/final-validation.json。


## 中断時の再測定と再開資料（2026-09-13T16:52:05+09:00）

- 利用者が作業を一時中断し、タイムスタンプ付きで詳細な引継ぎを残すよう依頼した。
  製品source、対応表、実データ、Git index、branch、稼働serviceは本記録作業で変更しない。
- 2026-09-13T16:45:18+09:00に両checkoutを測定。作業treeは18 tracked modified/65 untracked/0 staged、
  元checkoutは18 tracked modified/60 untracked/0 staged。同HEAD 8d12fa6979700f3ed281f06262a91cb25faa635c。
  詳細再開資料1件が増え、作業treeは18 tracked modified/66 untracked/0 staged、計84差分と確認した。
- 現mapの証拠checkerを再実行して終了0。reviewed gateは3 review/3 Widget reviewで期待どおり終了1。
  完了条件未達であることを再確認したのであり、全repo gateを再実行したものではない。
- 保存済みcold/recoveryのsource manifestと現sourceを照合。差があるのは記録対象中のmapだけ。
  両試験のmapは旧4ce42c272921615dbf0b64e5であり、現mapの全件受入は未実施。
- native Goalを読み取り、blockedを確認。登録文面は当初D01〜D04の履歴であり、
  後のユーザー包括承認と中断依頼は本資料へ保存。Goalの作成・変更はしていない。
- 作業treeをCWDとする他のcollector等は観測されず、元checkoutには既存Chrome DevTools関連processが残る。
  CWD観測だけで全hostのwriter不在を保証しない。既存processを停止していない。
- 根拠、未commit sourceの保全、process/portの観測、変更前docsは/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518へ保存。
  詳細手順は[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/docs/plans/active/ranking-daily-use/RESUME.md](RESUME.md)。
- canonicalの書込み・再開検査、文書metadata/link、差分・hash保全の最終結果は
  /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/validation.jsonと/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/pause-20260913-164518/final-audit.jsonに保存した。
  両canonicalのcheck-current/check-resume、metadata/link、git diff --checkと独立内容reviewはPASS。
  repo外の元checkoutリンクは平文の絶対パスへ修正して再検査し、canonical候補出力解析の初回失敗も記録した。
  引継ぎ検査の合格を製品の新たな受入や本番反映として扱わない。

## TradingView OSSの有限試行

ユーザーの「技術的に試行して」に基づき、独立環境で3つのOSSを試した。試行PASS、製品採用は未実施。

- shner 3.2.1: 固定参照531/531を765msで取得。3契約も取得可能。
- deepentropy 0.4.1: BTC3取引所＋未解決3契約を取得。change.15等のenumはchange|15等へ変換される。
- TradingView-API 3.5.2: BTC＋3契約を各80本取得。確定足308本のOHLC不一致0、
  同じTでの15分/1時間騰落率8比較すべて取引所と一致。BTC出来高は小数2桁丸めにより77比較で差。
- Screenerの進行中の足と、確定した直近窓では基準時刻が違い、NEX15分は−0.099305%対＋0.299103%。
  相対出来高の平均10本と現行中央値95/23窓、base出来高とquote売買代金も別の量。
- 同一契約・一定倍率なら騰落率では倍率が相殺される。契約単位表示を統合mapの数量審査と分離する案に
  技術的根拠を得たが、今回の依頼は試行であり、既存mapの受入条件を変更していない。
- metadataのbase_currency/pointvalueはBitget原資産数量の公式根拠にならず、review3は維持。
- RESTはScreener5要求＋取引所5要求、WS4契約を有限実行。製品code/依存/map、unit/DB/Git indexは変更なし。

詳細・固定commit・ライセンス留保・保存response・実行script・ランキングCSV:
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/oss-probe-20260913-170518/REPORT.md`。
常時稼働、全契約の履歴一致、quote turnover、D03、D04/D05はこの試行からPASSへ昇格しない。

## 資格判定v2の実装と受入（2026-09-16）

ユーザーは旧原則・完了条件の変更を許可し、続いて「実行実装」と指示した。
Q1〜Q4は原資産・固定参照の採用資格と、元数量換算・Widget対応を分ける実装・隔離受入である。
旧mapの未達記録を、新基準の成功へ読み替えていない。

### 実装と個別採用

- `ranking-map-v2`と`ranking-v2`へ更新。元倍率nullを許容し、行の`verified`の意味を
  原資産同一性・固定参照契約の資格へ限定した。同一性・参照のreviewは価格取得を拒否する。
- 全件ランキングgateを`--require-ranking-qualified`とした。旧`--require-reviewed`は
  元数量・Widgetも含む全確認として残し、現mapでは終了1を確認した。
- 証拠checkerは元数量の未確認台帳と、倍率nullの採用行の元ID・固定参照・独立根拠を照合する。
  台帳欠落・重複、identity根拠欠落、参照key差替えを拒否する回帰を追加した。
- 画面は数量換算とChart未確認の件数、選択詳細の数量制限、Chartの独立状態を表示する。
  数値・順位・4指標は確認済み参照契約から計算する。計算式、SQLite、取得Providerは変更していない。

| 対象 | 原資産・参照の確認 | 採用した固定参照 | 独立した未確認 |
| --- | --- | --- | --- |
| CHEEMS | BitgetのCheems metadataとBitget/Binanceの同一BSC CA、Aster/Binance指数を照合 | Binance 1000CHEEMSUSDT、倍率1000 | Bitget 1MCHEEMS数量倍率、Widget |
| NEX | BitgetのNexus metadata、Bybit公式告知の本文、Aster/Bybit指数の同じBitget NEX spotを照合 | Bybit 10000NEXUSDT、倍率10000 | Bitget 10000NEX数量倍率、Widget |
| RATS | Bitget 1000RATSUSDTのInfo表示とCMS応答がBRC-20 RATS・inscriptionへ結び付くこと、Aster/Bybit指数を照合 | Bybit 1000RATSUSDT、倍率1000 | Bitget 1000RATS数量倍率、Widget |

RATSの画面説明はCoinMarketCap/CoinGecko由来と明記されている。取引所画面と資産の対応確認に使い、
Bitget原数量の契約仕様とは扱わない。Bybit/Binance参照倍率は各社の明示された指数係数で確認した。
公式一次URL・観測時刻・identity fields・参照revisionは
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/qualification-evidence.json](../../../../apps/ranking-core/data/qualification-evidence.json)
の`rankingQualification`と`officialIdentityEvidence`、`indexComponents`へ記録した。

最終mapは`07bfd5c76b6fc8cbc882aeba`。元1,203契約・691行を保持し、変更行は3行だけ。
originalsは全件変更なし。参照対応534（Bybit482/Binance52）、未対応36、対象外121、行review0。
元数量未確認3、Widget未確認3、既存Widget対応531を保持する。

### Sourceと画面の検証

- Repository横断検証は終了0。専用の一時Postgresを使用し、終了時に当該containerを削除した。
  maintenance156、Market Core78、Ranking Core122、Web159、PC/Mobile E2E36が通過。
  Ruff・format・Pyrefly・生成schema/型・Svelte検査・build・文書checkerを含む。
  Market CoreのPyreflyには既存の抑制2件・非表示warning6件がある。エラーは0。
- 新規E2Eは変更前画面で数量注意表示の欠落による失敗、変更後で成功を確認。
  最初の試行はbundled Chromium不在だったため、repo既定のChromeでRED/GREENを取り直した。
- 実ProviderにつないだPC1440/Mobile390の画面で3銘柄を選択し、順位・数値・数量注意・Chart停止・
  未確認件数・横はみ出しなしを6ケース確認。JS例外・Widget script要求は0。
  履歴準備中の画面証拠であり、その時点の全534件準備完了を主張するものではない。
- 別のDecimal計算でBTC、SYN、1000PEPEと追加3契約の各3期間、計18比較が一致した。
  騰落率・native quote turnover・平常比・当日高安位置を照合し、daily平常比は未対応nullを確認。
- 元checkoutのsource・HEAD・indexは変更なし。作業treeのHEADとstage内容も変更なし。
  作業treeではindexバイト列に差があるがstage差分は0であり、index hash一致とは報告しない。

検証log・変更前保全・独立比較・実画面・OS隔離の証拠は
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841`
へ保存した。各検証の入口は次のとおり。

- `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/verify-local.log`
- `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/live-values.json`
- `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/live-ui.json`
- `/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/isolation.json`

### 有限の実Provider受入と完了判定

Q1〜Q4および改訂基準のD01〜D04はPASS。D05の稼働反映は未実施。
元数量換算3件・Widget3件は独立した未確認であり、旧全確認の`qualificationComplete`はfalseを維持する。

- 空stateから全534契約・3期間の連続3世代を確認（JST 19:37, 19:38, 19:39）。
- 保存済みstateの通常3世代（JST 19:45, 19:46, 19:47）、両Providerの実WS切断・再接続、
  75秒停止、再起動後3世代（JST 19:53, 19:54, 19:55）を確認した。各世代の有効数は全期間534。
- 12条件のAPI読取り前後で外部REST要求数が増えないことを、準備・通常・再起動後に確認した。
- generation処理の最大は1008ms、観測最大RSSは467884KiB。
  これは試験processの観測であり、本番cgroup制限の適用証拠ではない。
- 各試験は上限900秒。bubblewrapで専用stateだけを書込み可能にし、元Market stateを空のmountで隠した。
  専用state外の書込み拒否も実測した。port18769は準備用、18771は復旧用。
  復旧の初回port18769事前確認はEADDRINUSEで終了し、collector起動前に別の専用portへ変更した。
- 試験用collectorは有限runの終了で停止。実画面用のport18770プレビューも停止した。
  稼働unit、live DB、元checkout、commit/pushを変更していない。native Goalもこの作業では変更していない。

最終集計:
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/verification.json`

空state受入:
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/live-state/preparation.json`

通常・停止・復旧受入:
`/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/var/tmp/ranking/qualification-v2-20260916-190841/live-state/acceptance.json`

D05では配置するsource・map・Web/API・切戻し対象を確定し、実際の資源制限・画面・復旧を検証する。
元数量換算や追加3Chartを有効にする場合は、各機能の一次根拠・実表示を別途確認する。
