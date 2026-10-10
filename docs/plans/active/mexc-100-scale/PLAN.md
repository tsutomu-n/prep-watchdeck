# MEXC 10 → 50 → 100 銘柄の最適化と段階受入

timestamp="2026-10-10(土)_13:41 JST"
- 作成: `2026-10-10T10:30:00+09:00`
- 更新: `2026-10-10T13:41:18+09:00`
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
  50/100 registryの本番適用はprimaryが段階gate後に行う。互換release候補の準備は観測中にも進める。
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
- 11:15 JST（配置前）にSOL_USDTのversionが9925→9933へ変化。差分は公式hot symbol tagのisHot false→trueのみ。完全raw/旧定義を保全してsemantic比較の限定除外を追加し、現9933を独立再資格判定。b562348とmap 687bdf8450250a4f8343d51aへ切替済み。古いIDの復元は行っていない。
- 50件2h/100件24h観測と最終容量受入は未実施。isolated replayの追加90件groupIdはnullで、現singleton文字列を入れた場合も行数668は不変。summary増分0.77%、4詳細増分0.11%のserialization差を確認したが、その補正後性能は未実測。
- 既存maintenance/dataopsは10:07/10:04時点で復帰しており、過去失敗を現障害としない。
- 11:46 JST: 最適化済み10件の600秒通常運転はPASS。OOM/restart0、cycle最大3.197秒、入力age最大47.694秒、summary/detail p95 201.837/72.533ms、anonymous+kernel標本peak470.20MiB。容量の10分外挿は診断のみで、24h容量受入は未実施。実効registryを50件へ変更し次releaseを準備する。
- 11:51 JST: 3e3933eの50件registryを配置。専用writer停止中にhash固定の審査済みcatalogだけを保存し、実contractVersionでmap 0ac45f50a8e5861642d3428eを採用。旧資格・日時・history保持、1147 originals/618 rows、native-only review40・quantity4・Widget43（旧3保持）。ranking資格gateのexit1は未審査40件による想定失敗。11:53に価格/OI/Funding50件readyとnative singleton40件を確認。2h観測はまだ開始前。
- 隔離copyへ現singletonでevidence1世代だけ追加したprofileはcycle3.636秒、同時summary1要求3.594秒。既存1705世代・immutable全hashを保持。latest読取の全走査と一時sortを確認し、decision_at DESC,id DESCの複合indexだけを追加。latest SQL/保存後一致検証/schema1を維持し、旧DB読取・同時刻tie・query plan回帰を含むstorage/service8件とRuff/Pyreflyを通過。改善量は配置後の通常観測で確認する。
- 50件2h通常観測を 2026-10-10T02:55:57.056155+00:00 に開始。Attentionだけをindex追加版63591dfへ更新し、他serviceは50件版3e3933e・map0ac45f50a8e5861642d3428eを維持。観測中に100件source候補と最終横断gateを準備するが、100件本番拡大は2h判定後。
- 12:02 JST: 初回50件観測を360秒で中断し昇格証拠から除外。Fundingの独立取得後もDB反映が次60秒L1周期まで待つため、同じ7銘柄でsource age最大120.217秒・期限切れが90秒実測で再現。価格/OI欠測0。TTL90を維持したまま、2秒のFunding専用保存・L1とのwrite順序・native契約version競合を修正し、新しい2h観測を開始する。
- 100件candidate横断gateはMarket350/Ranking176/Attention78/Web266と必須check成功、E2E156成功/1既定skip/1失敗でraw exit1。mobile設定testがlive Attention8770の実Discovery候補を読むfixture隔離欠陥を特定し、専用port18870と空候補/判断fixtureへ修正。設定/Discovery desktop/mobile16 E2EとWeb checkが成功し、3426117をcommit/push。Funding修正後の最終release gateは未実施。
- Funding公開遅延修正の関連28件・Ruff/Pyreflyと独立reviewが成功。2秒保存、L1後着再結合、actual native version照合、二重cancel時のwriter drain、同transactionのFunding原文保全を確認。最終横断gateを実行中で、50件修正版は未配置。100件registry候補は別差分として保持し、50件再観測後まで本番へ配置しない。
- 12:27 JST: Funding修正版の横断gate exit0。Market355/Ranking176/Attention78/Web266、E2E157成功/既定1skip、Ruff/Pyrefly/schema/type/docs/buildが通過。12:02通常maintenanceのsettled Fundingでbatch/各eventの観測時刻不一致による失敗を確認し、MEXC分岐の二重時刻取得を最小修正中。12:19 dataopsはranking_original_identity_mismatchで失敗しており、実対象を確認するまで50再観測と100昇格を保留する。
- settled FundingはMEXCのHTTP完了後に時計を2回読む不具合を3行で修正。実store validatorでREDを確認した回帰を含む関連6件、Ruff/Pyrefly・独立reviewが成功。50件互換修正版としてFunding公開修正と配置する。dataopsのmismatchはKAIA/MAGIC/TAO/USの4 MEXC native-only行（03:15 catalog更新）に限定され、旧/current定義を確認中。通常maintenanceの修正後成功と新50件2h受入は未実施。
- MEXC公式仕様と4件のREAD ONLY差分を照合し、注文数量上限4項目とrisk tier内maxVol値だけをsemantic比較から除外。raw/full hash/旧version/未知tier情報を保つ関連20件（DB3件を含む）・Ruff/Pyreflyが成功。4現versionのみ再資格したmap候補1e2c8d5d1e282295468a36f9は50件consumer/replay/独立reviewを通過し、他1143originals/46資格/旧history全22filesとreview40/quantity4/Widget43を保持。source修正版と候補mapは最終照合後に同時配置予定で未採用。
- 12:44 JST: commit/push済み59671d2のtracked50releaseを全6serviceへ配置し、独立requalification map1e2c8d5d1e282295468a36f9を同時採用。配置直前の専用READ ONLY current roster1147/active50を新release consumerで照合、immutable map全26files hash一致。旧ID復元・migration・単独catalog persistなし。選択/workspace hashとmanual decisions不存在は不変。12:45に価格/OI/Funding50件readyを確認し、12:46:04 JSTから新50件7200秒performance観測と3秒間隔Funding観測を開始。旧360秒観測は引き続き不採用。100件source候補の最終横断gateを実行し、実50件2hとFunding/WS/recovery/dataopsの判定後にだけ100配置へ進む。
- 12:52 JST: 100件source候補の最終横断gateがexit0で終了。Market373/Ranking176/Attention78/Web266、E2E157成功/既定1skip、Ruff/Pyrefly/schema/type/docs/build成功。稼働中は59671d2の50件で、2h観測の完了予定は14:46 JST。100件registryとcurrent docsをcommit/pushしてtracked releaseを準備するが、2h終端とFunding/WS/recovery/dataopsが受入済みになるまで100件を配置しない。100件24h・容量受入は未実施。

- 13:09 JST: 修正後の通常maintenanceが成功（Funding 279/279、failure0）。新50観測の04:00 UTC（13:00 JST）の決済16件は欠測を保持し、同versionの新値へ最長61.582秒で復帰した実データを独立レビュー済み。通常freshとして扱わず、厳密な決済例外として記録する。
- 13:22 JST: 最新Funding記録で13:15 JSTの3version変更と約54秒のl1_missingを確認。12:46開始の観測は昇格証拠に不採用とし、100切替driverは起動していない。KAIA9976→9978/MAGIC9975→9979/US9974→9980のREAD ONLY全6定義でnormalized差分0、raw差分はisHotとtagIdListのみ。公式契約タグ定義と照合し、valid tagIdListだけのsemantic投影を修正、unit27＋隔離DB1・Ruff/Pyrefly・実3組replayが成功。現version3件の再資格mapと修正版50releaseを準備し、新7200秒観測をやり直す。2501b13の100件candidateはbuild済みだが、この修正を含む次候補へ置換予定。100件24h・最終容量は未実施。
- 13:31 JST: commit/push済みc805056のtracked50releaseと再資格map445f6cdfe65120105530afa1を全6unitへ採用。直前READ ONLY capture1147/50整合、37map files byte一致、他1144 originals/47資格/旧history全保持。旧ID復元・catalog persist・migrationなし、selection/workspace/manual decisions保全。起動直後39秒の観測はAttention staleのため不採用。ready/partial復帰後の13:33:05 JSTから新performance/Funding7200秒観測を開始（完了見込み15:33:05 JST）。最初の標本は価格/OI/Funding50件、performance違反・未観測項目なし。100件candidateの最終source gateはタグ修正を含めて実行中。
- 13:34 JST: タグ修正込み100件sourceの横断gateがexit0（Market384/Ranking176/Attention78/Web266、E2E157成功/既定1skip、必須静的/schema/type/docs/build成功）。初期9 API標本のdetail p95=2655.876msは、同rawを保持した29標本再計算で88.547msへ復帰。同期世代更新と1件の409遅延が一致しており、期間全体のp95で最終判定する。単一SQLite connectionを持つためworker化は接続責務の変更を伴う。現時点で範囲を広げず、終端p95超過なら再検討する。新期間のWSは2×25 ACK・失敗/再接続/gap0、自然dataops成功・identity診断0、既知warning4件だけ。100昇格と24h/容量受入は引き続き未実施。
- 13:40 JST: 100件source d81614eをcommit/pushしtracked release build/hash比較PASS。source gate後はdocs checkpointだけ更新する。条件付き継続処理をPID1820215で開始し、receiptは`/home/tn/watchdeck-local-archive/mexc-100-scale-20261010-1025/finite-acceptance-tag-run/receipt.json`。開始時PENDING/waiting_stage50、昇格承認fileなしを確認。policy SHA bc4a2d9508b2de0861e654435b816f5ea1880816e8172b828dce9fe2a1c59ecdはrelease/map/6unit設定/保護対象/観測先/審査済み例外を固定し、未来の実測を承認済みにしない。新50観測の7200秒終端とFunding/WS/成熟candle全件/dataops/通常maintenance/現roster/保護対象が合格した場合だけ、100配置と86400秒性能・Funding・容量観測へ進む。途中の累積API p95だけは期間終端まで保留し、その他の失敗と終端gateは維持。未達はATTENTION_REQUIRED/NOT_ACCEPTEDを保存し、100配置後の測定失敗では健康なserviceを維持する。最大28時間の有限処理で通知・再帰Codex・新daemonなし。最終受入は現時点PARTIAL、100件24h・30日予測＋50GiB容量条件は未実施。
