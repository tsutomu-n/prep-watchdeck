# デイトレ判断フローとMEXC接続

timestamp="2026-10-10(土)_07:38 JST"
- 作成: `2026-10-10T06:41:00+09:00`
- 更新: `2026-10-10T07:38:41+09:00`
- 検証: `未検証`
- 状態: `実装計画`

## Goal / Global Constraints

既存Marketsで候補発見→最大4件比較→実Venue確認→監視/見送りをつなぐ。
MEXC public crypto USDT linear perpetualを第四Venueに追加する。
ブラウザを閉じてもAttention service稼働中は条件履歴を保持する。
自動注文、外部通知、任意条件builder、他の新Providerは対象外。
本番state/DB/serviceとJustPassには触れず、CI/push/PR/deployは実行しない。
作業開始HEADは9910617、branchはai/daytrader-mexc-20261010-0641。
元checkoutはclean。所有ファイルを分けて並行実装し、primaryが統合検証とcommitを行う。
子agentはcommit/branch操作をせず、担当外ファイルを変更しない。
source、commit、本番反映、実データ受入を区別する。

## Task 1: MEXC Market Core

Ownership: apps/market-core（testsとdataを含む）、Market用schemas、scripts/market。
Catalog/L1/OI/funding/1m candles/history recovery/selected depth+trades/保存保守を全て接続する。
Venue=mexcを明示追加し、scheduler/store/CLI/archive/maintenanceの3件固定を解消する。
未知VenueがAster等のelseへ流れないようにする。
Catalog数量はcontracts、contract_multiplier=Decimal(contractSize)、amount_step=volUnit。
base数量換算はexact versionの係数を使用し、価格には掛けない。
RecoveryTarget、selected validation/store SQL、group eligibilityにもこの契約を通す。
既存3Venueのbase+1は維持。数量変換とcross-market identityの証拠を分離する。
crypto分類/資産/価格単位を確認したevidenceだけ採用し、未知/株式/金属/FXは理由付き除外。
typeLabel=0でもXAUがあるのでcrypto判定に使い切らない。契約係数変更は新versionで再確認。
raw保存を保ち、確認済み表示/fee/leverage fieldだけsemantic hash比較から除外し、未知fieldは残す。
API root=https://api.mexc.com、WS=wss://contract.mexc.com/edge。
REST contract/detail/country,ticker,funding_rate/{symbol},kline/{symbol},depth/{symbol},deals/{symbol},funding_rate/history。
公開接続preflightは済み。BTC contractSize=.0001、ETH=.01は観測例であり固定定数にしない。
WS sub.depthはbegin/end/version範囲、数量はabsoluteで0削除。snapshot+連続deltaで維持し、gap/reconnectは無効化。
sub.dealのiを重複排除。WS klineにclosed flagなし。確定性の根拠を既存契約へ明示的に対応させる。
Funding符号/collectCycle/nextSettleTimeを保持し8h固定にしない。
最小fixtureで換算、非crypto除外、version変更、板gapと重複約定、復旧経路を検証する。
数量semantic/evidence registryのinterfaceをTask4へ早期に通知する。

## Task 2: Attention Discovery

Ownership: apps/attention-core、scripts/attention、Attention/Discovery schemas。
既存single-writer loopだけで最新raw projectionとepisodeをSQLiteへ保存し、GET /discoveryを追加。
Market artifactとRanking API以外を読まない。新Provider、user-workspace読取、新serviceは禁止。
Policy ID=discovery-reference-turnover-15m-v1。
eligibleなverified exact-original rowsで、Ranking.turnoverComparisonの昨日/一昨日同時刻比が双方>=3。
15m return>=2%上昇、<=-2%下落、他は売買代金増加。価格欠損は方向不明で成立事実を保持。
方向変化だけで新episodeを作らない。browser表示設定とは別の固定条件として示す。
matched/not_matched/unknown。新Ranking cutoffで一度だけ評価。
比較可能な連続世代の非成立→成立だけnew。起動直後/欠測後は初回確認/再確認。
firstObservedAt,lastConfirmedAt,連続確認数,policy,exact identity,source generationを保持。
欠測/停止は解除でなく観測中断、空白を継続時間へ加算しない。identity/policy変更を継承しない。
最新rawは最新世代へ置換し全件immutable履歴を増やさない。既存5分evidenceと/attention契約を保全。
OI/Funding/native価格の値・source/window/unit/qualityを個別表示できるprojectionにする。
GETは最大4対象絞り込み、履歴50件cursor pagination。GETにwriter副作用を持たせない。
active episodeは保持。終了履歴は7日/最大10000件、古い終了履歴から除去。historyAvailableFromを返す。
最小の遷移/重複世代/欠測再開/retention/GETテストと関連既存testで検証。
JSON contractを最初にTask3へ通知し、生成型のsourceを確定する。

## Task 3: Web workflow and MEXC readers

Ownership: apps/web（generated型はprimaryが最後に生成）、Web tests。
DESIGN.mdとSvelte関連skillを適用。既存Markets内に最大4候補の比較欄を実装。
順位低下/条件解除でも候補維持。pin操作はselection POSTを送らず、明示確認時のみ既存実Venueへ遷移。
検出理由/発見後変化/source/時刻/単位/欠測を近接表示、参照市場とnative値を混同しない。
user-workspace v2へpinsを追加しv1 favorites/views/revisionを保全。現64KiBに判断historyを詰めない。
Web-owned別repositoryにwatch/skip,理由,時刻,exact target,episode,表示時の根拠snapshotを保存。
manual historyは自動削除せず1000件または16MiBで新規保存拒否。重複送信とatomic書込/競合を扱う。
skipはepisode単位、次の成立は再表示。自動履歴期限後もmanual snapshot単独で読める。
GET /api/discovery proxyを追加、旧Attentionで未対応でも既存Marketsを維持し機能利用不可を表示。
固定監視15m/両日3x/方向2%を明示し既存browser thresholdを変更しない。
MEXCのVenue UI/filter/Chart history/price-change/source validationへ明示branchを追加。
reference originals変更時は保存対象を保持し再確認UI。黙ってお気に入りtargetを更新しない。
最小unitでv1 migration/保存上限/競合/skip、E2Eで4件保持/selection保全/遷移/再読込/DesktopMobileを検証。
Task2とAPI/schema interfaceを連絡してから消費する。package型生成scriptへの追加は許可、生成実行はprimaryと調整。

## Task 4: Ranking MEXC qualification and integration

Ownership: apps/ranking-core、scripts/ranking、ranking-response schema。
Venue=mexc reader-first対応。mapping.extract_rosterがsource_invalidにならないようにする。
ProviderはBybit/Binanceを維持。OriginalInstrument.multiplierは整数asset-price identityでcontractSizeと混同しない。
MEXC exact instrument/versionの確認済みmapping、initial-map/initial-roster/qualification-evidenceを一貫更新。
Task1とidentity/evidence registryを協調し、未知はunmapped/exclusionのまま見せ、symbol推測で補完しない。
現在のevidence生成/検証経路を使う。既存qualificationを改ざん・無効化してgreenにしない。
collector入力→Ranking→Attentionのid/version対応を実データで確認できる最小隔離入力を準備する。
最小のMEXC reader/mapping/quantity-vs-price倍率テスト、既存map/schema検証を実施。

## Validation / Completion / Rollback

必要な最小pytest/Ruff/format --check/Pyrefly、schema/map checks、Web Vitest/check/buildと関連E2E。
統合後scripts/verify-local.shを一度実行（専用一時Postgres、現役DBは使用しない）。
実装準備後、専用state/DB/portで全MEXC取得と代表銘柄Chart/板/約定を60分観測する。
更新頻度、欠測、rate limit、再接続、容量増加を記録。短時間API到達を受入代用にしない。
docs/currentへsource仕様を反映し、source完了時に必要差分のみcommit。
本番未配置と本人操作受入未実施は別に明記する。push/PR/CI/service操作をしない。
reader先行配置を要求しrollbackも新schema対応版でMEXC取得を無効化する。旧readerへ盲目的に戻さない。

## Checkpoint

- 4 taskのsource実装と独立reviewを完了。文書は現行sourceへ更新済み。本番には未配置。
- Repository全体check: Python/型/schema/map/Web unit/check/buildは通過。
  全体E2Eは153 passed / 2 failed / 1 skipped。表示密度とmobile test待機を修正し、該当8ケースは再実行PASS。
  同じfull commandがexit 0だったとは扱わない。
- 実MEXCで10契約のL1/数量換算/足/Ranking/Discovery/Webを確認。10件の保存足とREST履歴も一致。
- 実観測でcached REST板のversion gapと非集約depthによるqueue飽和・切替cleanup失敗を確認。
  native commit bridgeと200ms集約配信へ修正。短い実BTC→ETH切替・正常終了はPASS。
  修正前の失敗証拠は隔離evidenceへ保全。最終sourceの60分観測を07:26 JSTに開始し、
  強制切断後の復旧と10分時点のBTC→ETH切替を確認済み。08:26 JSTまで観測する。
- 実BNB成立episodeで監視/見送り、表示根拠とexact identityの保存・再読込・Mobileを確認。selection writeなし。
- 既存577行の通常/5分保存回を各1回測定。全応答14.8 MiB、peak RSS約425 MiB。
  32 MiB response cap内だが、512 MiB cgroupでの長時間受入は別途必要。
- 未完了: 最終60分観測、容量/再接続/切替/正常終了の集計と完了plan整理。sourceをlocal commitにまとめる。
- 境界: MEXC採用は確認済み10契約。既存3数量/3Widgetは未確認でstrict reviewed gateはFAIL。
  本番配置、本人の判断速度、30日evidenceは別受入であり今回の完了へ読み替えない。
