# MEXC 10 → 50 → 100 銘柄の最適化と段階受入

timestamp="2026-10-10(土)_11:27 JST"
- 作成: `2026-10-10T10:30:00+09:00`
- 更新: `2026-10-10T11:27:30+09:00`
- 検証: `未検証`
- 状態: `実装計画`

## Goal / Global Constraints

ユーザー承認済み計画に従い、取得・表示を最適化し、既存MEXC 10銘柄を保ったまま
取得時点の24h売買代金順に審査した90銘柄を追加する。crypto / USDT / linear perpetualだけを
採用し、分類・原資産が未確認なら次候補へ進む。段階ごとに固定し、自動入替はしない。
Ranking参照同一性を推測せず、native-onlyもcoverageと理由を保つ。

原workspaceの既存未commit 4ファイルを保全し、専用worktreeで作業する。
CI・PRは使わない。実装・commit・対象branchへの通常push・指定serviceの本番切替は承認済み。
既存保存evidence削除、retention変更、JustPass DB操作、未知数量/Widget資格の承認は対象外。
各taskは所有ファイルのみ編集し、同じGit indexの同時操作を防ぐためcommitはprimaryが行う。
局所回帰とpackage必須check、最終releaseで横断gateを1回行う。source成功と実データ受入を分ける。

## Task 1: Funding独立取得と保存契約

所有: Market Coreのmodels.py、store.py、universe.py、archive関連、sources/mexc.py、service.py、
migrations/0006*、Market Funding関連tests、universe schema。他task所有のbudget・WS・registry、
market_metrics.pyは編集しない。service.pyはこのtaskが所有しprimaryの時刻修正要求を統合する。

- Ticker / price / OI公開は銘柄別Funding HTTPを待たない。独立Funding loopで毎秒2件開始、
  最大4並列、巡回目標60秒、TTL90秒。観測時刻は実際の取得時だけ更新。
- expiry、取得失敗、次回決済時刻通過、catalog契約version変更でFunding4値をnull＋reasonにする。
  cache再利用で鮮度を偽装しない。Ticker必須値の価格・時刻・bid/ask・OI・amount24・数量換算が
  正常な行だけ明示的funding-only partialにし、価格比較へ参加可能にする。他partialを緩めない。
- migration0006でlatest_market_state / market_state_1mへnullable funding_source_at、
  funding_observed_at、funding_valid_untilを追加。旧行はnull、funding_eventsはsettledのまま。
  MarketObservation→store→UniverseRecord→artifact/schema→archive/export/readbackへ接続。
  valid-untilはsource/observed TTLとnext settlementの最小。publisherとreader両側で期限を守る。
- Market consumerのreference medianはactive / 同cycle /120秒 /2venues /skew30秒 /
  quote currencyの既存制約を維持し、正常Tickerのfunding-only partialだけ追加許可。
- Task2の共有budget呼出はFunding lane、catalog/ticker/selectedはforeground lane。
  Task2とのHTTP interfaceは直接連絡して確定し、HTTP retryもbudgetを通す。
- 最小回帰: 遅いFundingでもTicker公開、expiry/settlement/contract変更、invalid ticker排除、
  旧行nullと旧archive読み戻し。uv / Python3.13、関連pytest・Ruff・Pyrefly。
- Web/Attention側Funding期限readerはprimaryが統合する。必要な契約変更を報告する。

## Task 2: 全取得元共有予算とCandle WS分割

所有: 新しいMarket共有budget module、sources/mexc_candle_stream.py、MEXCのHTTP call site
（Task1のsources/mexc.py / service.pyを除く）、Web MEXC history/price-change経路のserver module、
関連tests。config.pyやservice.pyの変更はprimary/Task1へpatch要求し無断で同時編集しない。

- 新常駐serviceを作らずSQLite budgetをPythonとBunで共有する。
  合計8 calls / rolling2秒、Funding4、foreground2、recovery/maintenance2の固定lane。
  全HTTP attempt/retryを通し、429 cooldownを同じDBへ反映する。
  waitとHTTPは短いSQLite transaction外、busy/corrupt/unavailableは期限付きfail closed。
- 絶対pathのPREP_WATCHDECK_MEXC_BUDGET_DBを同一egress processで共有する。
  production business DBと分離する。隔離stateも実Provider使用時は同予算を使う。
  Node Vitestでbun:sqliteを直接loadせずadapter注入し、Python/Bun実multiprocess試験を1つ行う。
- Candle WSは25symbols/connection（100で4）、全connection合計5subscription commands/s、
  ping15秒、ACK確認、connection単位のbackoff+jitter。1connection失敗で他connectionを切らない。
  数値は設計値で公式上限と説明しない。公式WSの現行ACK formatは一次sourceを確認。
- 最小回帰: lane/shared cross-process limits、429 shared、budget障害停止、1WS障害の隔離。
  uv / Python3.13、bun、関連pytest/unit・Ruff・Pyrefly。広いgateはprimary。
- 既存規約を優先しsecretを出力しない。実production unitやstateへは変更しない。

## Task 3: Discovery一覧と比較詳細の分離

所有: Attention discovery models/store/api/engineの必要箇所、Discovery Web UI/client/API route、
discovery summary schema/type生成設定、関連tests。Market、Ranking、Web MEXC取得は編集しない。
generated types再生成はprimaryと時刻調整する。

- /discovery-summaryとWeb /api/discovery-summaryを追加し、独立discovery-summary-v1契約にする。
  generation/cutoff/status/direction/identityと一覧表示に必要なlabelsのみでraw subtreeを含めない。
- SQLiteで最新detailをasset IDにより直接取得可能にし、generation metadataと同一transactionで
  更新する。巨大JSON全体やjson_each全走査を詳細取得の都度行わない。
- 既存/discoveryとdiscovery-response-v1を維持。filtered detailに任意generationIdを追加し、
  不一致は409 discovery_generation_changed。既存evidence/history/decision snapshotは保全。
- UIの15秒pollはsummary＋最大4件detail。summary/detail generation競合は1回再取得し、
  再競合時は旧viewと更新待ち表示を維持してdecision/selection確認を止める。pinsは保持。
- 旧SQLiteデータの読取と互換rollbackを維持し、保存済み内容を削除しない。
- DESIGN.mdを読み、Desktop/Mobile、Markets/Universe/Rankingへの影響を限定する。
  最小回帰: summary size/absence raw、generation conflict、4detail、saved evidence preservation。
  関連pytest/unit、Ruff/Pyrefly、Web check/build、関連E2E。最終gateはprimary。
- 100銘柄60世代の実保持量に基づく隔離capacity測定に必要なprobe入口を報告する。

## Task 4: 100銘柄審査と追加可能なmap

所有: sources/mexc_evidence.py、MEXC evidence JSON、scripts/ranking/prepare-mexc-map.py、
必要なRanking map/evidenceと関連tests。他Market源、models、service、Discoveryは編集しない。

- existing10を維持し、公式catalog＋取得時点を保存したMEXC amount24降順で追加候補を審査する。
  crypto / USDT linear perpetualと原資産・price unitを公式asset pageや正確なfutures linkで確認。
  typeLabel/symbolだけで分類せず、未確認候補は次へ。90件の根拠と除外理由を保存する。
  contractSizeのquantity係数とasset price multiplierを混同しない。
- 審査済み10 / 50 / 100の固定registry source bundleを作れるよう成果物を用意する。
  個別activation flagや日次自動入替は追加しない。最初の実装releaseは10件を保ち、
  50/100 registryの適用はprimaryが段階gate後に行う。
- prepare-mexc-mapは追加・再実行対応、既存根拠/review日時/定義を保持、同入力で重複/不要version
  変更なし。structural identity変更は再審査要求。現在roster全体のexact coverageを維持する。
- Bybit/Binance等の同一性が確認できない新銘柄はreference:null＋理由＋根拠を持つnative-only。
  既存quantity4/widget3 unknownを承認へ変えず、qualified gateを弱めない。
- 実production contractVersion IDは各切替後primaryが再採取する。架空IDや過去IDをcurrentとしない。
- 公式資料取得は低頻度で行い、bulk REST ticker/catalogを再利用する。必要な現在仕様はweb一次source。
  ローカル検証でproduction writerやserviceへ変更しない。
- 最小回帰:10→50→100追加、同入力rerun、existing evidence保持、native-only coverage。
  schema/map evidence/require-reviewed auditを実行し、既存/新規unknownの想定失敗を隠さず分ける。

## Task 5: 時刻判定、統合、段階実測（primary）

Market metricsのcandle cutoffは取得開始で固定し、future validation / generatedAtはsnapshot読取後の
時刻を使う。分境界でもcutoffを再計算しない。真のfutureは拒否しfield/timestampをbounded診断へ残す。
service.py変更はTask1へ依頼する。最小回帰は後着受信、分境界、真future＋診断。

全reader（Web/Attention/dataops/archive/maintenance）のFunding時刻契約を統合し、
互換reader→migration0006→optimized10 writerの順で配置する。rollbackはv6互換readerを維持。
実運用drop-in/release/DB stateを保全し、source SHA・runtime path/hash・map versionを別々に記録する。

| 段階 | 受入 |
|---|---|
| 隔離 | 既存保持量再現、100銘柄、60世代、summary＋4detail |
| optimized10 | reader先行、schema6、予算共有、連続更新、既存manual control保持 |
| 50 | 2時間通常運転 |
| 100 | 24時間通常運転、通常maintenanceを含む |

共通: OOM/予期しないrestart0、cycle<60s、input freshness<=150s、summary/detail p95<=1s。
Attention anonymous+kernel peak目標は768MiBの80%以下。超過時はprofile後に進行判断し、
file cache込みの総量だけで失格にしない。429/WS gaps/Funding availability/recovery backlogも測定する。
100件24hのSQLite/WAL/immutable/Market増分を分け、30日予測＋50GiB空きを容量gateとする。
予測を30日実測とは呼ばない。不足なら100受入保留、evidence削除やretention変更は行わない。

## Rollback

MEXC取得停止→直前段階registryへ→単一writerでcurrent catalog→現contractVersionでmap再資格→再開。
旧ID mapの単純復元・DB downgrade・evidence/履歴削除はしない。互換readerと旧releaseを保持する。

## Checkpoint / 未解決

- 2026-10-10 10:30 JST: 承認済み計画を開始。base b6259d3、専用branch ai/mexc-100-scale-20261010-1025。
- original4差分を外部archiveへhash/patch保存し、sourceへの混入を防止。
- 追加90件の審査と固定10/50/100 registry、Funding/保存/共有予算/WS/Discovery/時刻判定を実装。独立reviewで検出したPython/Bun内部HTTP retry、WS malformed symbol、履歴再展開、native-onlyのMarket共有group混入を修正し、境界回帰を通過。
- 旧daytrader-mexc-hardening planは本計画へ置換。maintenance/dataopsの復帰済み障害は再修正せず、Attention継続運用と容量受入を本計画の段階gateへ引き継ぐ。既存数量/Widget未確認、30日prospective evidenceは引き続き別受入。
- 横断gateはMarket345、Ranking176、Attention76、Web265 unitと必須check通過、E2Eは156成功/1既定skip/1失敗でraw exit1。既存JST設定のhydration raceを再現し修正後、Web266 unit・check/build・関連E2E16件が通過。raw gate全成功とは記録しない。native-onlyの追加16回帰・Ruff/Pyrefly・100件registry監査も通過。
- 隔離capacityは保持済み1645世代を複製し100MEXC/全1197原本・60世代更新。cycle p95 4.208秒/max5.367秒、一覧＋4詳細p95 29.761ms、RSS high-water 549.047MiB、旧evidence hash保持。加速replayであり実運転ではない。専用cgroupのkernel peakとWeb proxy並行負荷は未観測でPASS WITH ISSUES、live段階で確認する。
- production前の専用PG dumpとAttention SQLite backup・unit/control/workspace保全を確認。b49d71dをcommit/pushしtracked archiveからbuild。11:20 JSTに互換reader、migration0006、10件writerを切替。Market/Ranking/Attention/Webとmaintenance/dataopsのsourceを同releaseへ接続、共有予算を配置し10件の価格/OI/Funding readyを確認。元4ファイルとselection/workspace/manual decisionsの保全をhashで確認。
- 11:15 JST（配置前）にSOL_USDTのversionが9925→9933へ変化。差分は公式hot symbol tagのisHot false→trueのみ。完全raw/旧定義を保全してsemantic比較の限定除外を追加し、現9933の独立再資格candidateを準備中。古いIDを復元しない。50件拡大はこの確認と10件連続観測の完了後。
- 50件2h/100件24h観測と最終容量受入は未実施。isolated replayの追加90件groupIdはnullで、現singleton文字列を入れた場合も行数668は不変。summary増分0.77%、4詳細増分0.11%のserialization差を確認したが、その補正後性能は未実測。
- 既存maintenance/dataopsは10:07/10:04時点で復帰しており、過去失敗を現障害としない。
