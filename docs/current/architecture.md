# prep-watchdeck 現行アーキテクチャ

timestamp="2026-10-10(土)_12:22 JST"
- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-10-10T12:22:30+09:00`
- 検証: `2026-10-08T16:04:27+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書はRepositoryの現行実装を記述する。稼働中の配置versionは運用記録とunitから別に確認する。
現在のprocess数、DB、artifact数、poll周期、selection数等を将来のWatchdeck全体へ永久固定しない。
製品境界は[`product-boundary.md`](product-boundary.md)を正本とする。

## 現行Process境界

```text
Bitget / Hyperliquid Core / Aster / MEXC public API
                  |
                  v
        watchdeck-market service
          |       |        |
          |       |        +-- selected group WS
          |       +----------- catalog / L1 / candle
          v
 dedicated Postgres 17 ----> confirmed Parquet archive
          |
          v
 atomic JSON artifacts <---- SvelteKit Web
          ^                       |
          +-- control/selection --+
          +-- past-notes ---------+
```

- `prep-watchdeck-market-db.service`は現在の専用Compose project/DBを所有する。
- `prep-watchdeck-market.service`は現在catalog、L1、candle、selected stream、DB write、artifact発行を1 processで行う。
- 任意のnative metrics投影は同時に1つの子processで実行する。子processがread-only snapshot用の接続と専用lockを所有し、10秒timeout時は回収してから次の投影へ進む。既存4 artifactと収集laneを停止させない。
- Bitget短時間activityは別の60秒周期taskと子processで、保存1分足の必要な窓だけを
  read-only repeatable-read Postgres transaction内で集約する。外部取得・DB writeを加えず、
  既存metricsの最短5秒周期、基幹4 artifact、Ranking Coreの収集・応答契約から独立する。
- 現行WebはJSON read modelを読み、Postgresへ直接接続しない。
- maintenance timerはFunding sync、archive/readback/retentionを実行する。

このprocess topologyは現行runtimeの安全なbaseline。将来のranking worker、Stocks core、model service、追加artifact、
remote API等を必要に応じて別process/bounded contextとして追加できる。

他projectのDB/container/stateを共有しない原則は維持する。

## 現行Collector lane

### Catalog / Identity

Catalogは現在15分周期でVenue別に取得し、成功sourceをSCD2保存する。source kind、endpoint、payload hash、
observed/source time、capability、exclusion reasonを保持する。

既存3 Venueのauto-groupはactive crypto linear perpetual、base完全一致、base数量、multiplier 1、
Venue内候補1件を要求する。MEXCは確認済みのnative資産・価格単位・数量定義を
`verified_native_contract`として扱い、exact versionの契約係数でbase数量へ変換する。
実効registryは既存10件と追加40件の審査済みUSDT perpetual、計50件を固定採用する。
未審査・非crypto・定義不一致を推測でgroupへ入れない。追加40件と100件段階用の残り50件はnative資産だけの
審査結果を持ち、他Venueとの同一性を確認するまでは`native:mexc:<exact source symbol>:linear-perp`の
単独groupを使う。参考mark比較やVenue内衝突の推測へ混ぜず、価格・OI・Chart・手動selectionは保持する。

将来の別asset classやexplicit mappingは別contractで追加できる。

### L1

現在は60秒grid、single-flight、Venue fetch deadlineを持ち、一部Venue障害を他Venueへ波及させない。
前周期値をfreshとして再利用しない。

周期/deadlineは現行capacity値で変更可能。

### Candle

現在のsourceは4 Venueからfinished/confirmed/derived-final 1分足を収集し、queue/batch writerでPostgresへ保存する。
version境界、unknown version、invalid barを安全側に拒否し、gapを捏造補間しない。
MEXCのWSにはclosed flagがなく、分終了後5秒を基準とする導出確定を`derived_final`として区別する。

将来、別timeframe/source/backfill laneを追加できる。

MEXCのCurrent FundingはTickerとは独立して毎秒2件開始・最大4並列で取得し、60秒巡回を目標にする。
取得済みFundingは2秒周期で変更分を保存し、次のL1周期を待たずartifact更新を通知する。
Catalog・L1・Funding writerの順序を保ち、L1保存時はlock取得後の最新Fundingを再結合する。
契約のnative versionが一致する取得根拠を同じtransactionで保存し、価格・OIの時刻や標本数は変更しない。
Funding期限切れは価格・OI公開を止めない。Candle WSは25銘柄/接続、全接続合計5購読/秒、ping15秒。
ACKを確認し、失敗した接続だけをbackoff/jitterで再接続する。これらの数値は設計値で公式上限ではない。

### Settled Funding

現在のmaintenanceは有効なVenueのsettled fundingを同期する。現在値/estimatedとsettled historyを区別し、version boundary、
idempotency、conflictを検証する。

48時間catch-up等は現行runtime値。より深いhistorical laneを別設計で追加できる。

### Selected market

現在Webはselection commandをlocal fileへatomic writeし、market serviceが1 groupを購読する。
現行値は500ms debounce、15分TTL、5分heartbeat、旧subscription cleanup、CLOB depth/trade等。
MEXC板はnativeの200ms集約差分を使い、REST snapshotが遅れている場合は最大1,000件の
`depth_commits`から欠落・重複のない連続鎖を確認する。WSとの同期が成立するまでreadyにせず、
gap・切断時は板を無効化する。受信したraw envelopeとsnapshot・bridgeの根拠を保持する。

1 selection、20 depth、100 trades等は永久上限ではない。複数selection、pinned/ranked capture、単独instrument detail等を
将来追加できる。

## Storage truth

現在:

- Postgres: current/recent catalog、identity、collector run、market state、candle、funding、selected、manifest
- Parquet: confirmed normalized history
- JSON: Web用再生成可能read model
- local files: selection control、Past Note等

新しいranking features、model outputs、Stocks、journal等は既存tableへ無理に詰め込まず、必要に応じて別dataset/schemaを
追加できる。

## Artifact lane

基幹read modelはstate rootの`artifacts/`へ次の4 JSONを同一filesystem内でatomic publishする。

- `universe-snapshot.json`
- `market-chart.json`
- `selected-market.json`
- `service-state.json`

任意の`market-metrics.json`と`native-activity.json`は基幹4 artifactへ混ぜず、個別に発行する。
後者はBitgetの現行契約版ごとの15分・1時間のquote turnover、直近4窓、同時刻の過去日比較を保持する。
Webの`GET /api/native-activity`はこのartifactだけを読み、参照ランキングへnative値を書き戻さない。

Webはschema validationに失敗したartifactを推測で補完しない。

**4 artifactは現行構成であり永久固定ではない。** Ranking、prediction、Stocks、portfolio等の新artifact/APIを追加できる。

## State境界

現在の標準rootは`PREP_WATCHDECK_MARKET_STATE_DIR`。Postgres、archive、artifact、control、notes、lock等を配置する。
E2E/smoke/shadowはproductionから隔離する。

path、port、DB engine、single-host構成は現行runtime値。local-first原則を保ちながら将来変更できる。

## Architecture拡張原則

- 現行Perp contractを壊す必要がない新domainは別app/service/schemaを優先する。
- `未実装`を理由に共通base class等を先行汎用化しない。
- 2つ以上の実装で実際に共通化価値が確認できた部分を後から抽象化する。
- source failure、model failure、ranking failureを既存market ingestion全体へ波及させない。
- provenance、quality、unit、identity、timestampを新laneでも維持する。
- production state/DBとtest/shadow/他project資源を隔離する。

## Chart履歴の取得

Webの`GET /api/chart-history`は検証済みUniverseのactive grouped instrumentだけを解決し、
選択したVenueのnative時間足を取得する。Bitgetはv2の`candles`と`history-candles`、
Hyperliquidは`candleSnapshot`、Asterは`klines`、MEXCは公開host `api.mexc.com`の
`/api/v1/contract/kline/{symbol}`を使う。日足はUTC 00:00開始へ揃え、Bitgetでは`1Dutc`、
MEXCでは`Day1`を指定する。Webへ取引所の秘密API keyを追加しない。

1ページ最大500本、server cacheは30秒・32件、同時取得は8件までで同じ要求をまとめる。
HTTP開始間隔はWeb process内でVenueごとに全銘柄・時間足で共有し、Bitgetは1秒以上とする。
MEXCは既存のprocess内100ms以上に加え、Market/Web/recovery/maintenanceが同じSQLite予算を使う。
rolling2秒に合計8回、Funding4・foreground2・recovery2の固定枠とし、再試行も消費する。
429 cooldownを共有し、予算DBが不通なら無制限取得へ切り替えない。
1 HTTP requestは10秒、待機を含むページ全体は30秒でtimeoutする。最新を60秒ごとに更新し、
過去へのスクロールまたは追加ボタンで古いページを取得する。Browserは1銘柄・1時間足につき
最大10,000本を保持する。取得量は取引所の配信範囲に依存し、DBの8日保持には依存しない。

この履歴は表示用であり、Postgres・Parquet・既存4 artifactへ書き戻さない。
`market-chart.json`はcollectorが保存した1分足の集約read modelとして引き続き検証するが、
画面の長期Chartはnative履歴を描画する。native履歴にcollectorのSCD2履歴や
`confirmed` / `derived_final`の判定を付け替えない。

## 指定時刻からの約定騰落率

Webの`GET /api/price-change`は同じUniverse照合・native candle取得を使い、指定したJST時刻の
直前の確定1分足と最新の約定1分足を少量取得する。基準価格を日次anchor・契約version別に再利用し、
最新価格のcacheと取得中要求は、設定時刻と独立した取得開始分ごとのkeyにする。分をまたいだ旧要求を
新しい日次基準へ再利用しない。Bitgetの開始間隔はChartと同じqueueを使う。
可視行と選択銘柄だけをBrowserから最大2要求で取得し、全Universeの定期一括要求を避ける。

設定はBrowser単位のHH:mmで既定00:00。Collectorの状態・artifact schema・DB接続を増やさず、
ユーザーごとに異なる時刻を選べる。約定価格同士の比率であり、L1のMarkや参考中央値へ混ぜない。
native APIの欠測・鮮度は騰落率欄の理由として示し、Market Coreの品質判定を書き換えない。

## 独立したデイトレランキング

/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core/ は、Bybit・Binanceの公開USDT perpetualを
別processで継続取得する。元Venueから価格・売買代金を補完しない。既存artifactからは
名簿作成時にidentityだけを抽出し、確認済みmapとして保存する。価格・売買代金の通常収集は
保存済みmapで動作し、元のcollector、Postgres、Parquet、Selection、Past Noteへ依存しない。
名簿の鮮度だけは、毎世代に元stateの`universe-snapshot.json`と`service-state.json`をread-onlyで照合する。
完全で新しいcatalog取得と全original identity/versionのfingerprint一致を確認できた場合だけ、
応答の名簿観測日時を更新する。参照契約・数量・mapの審査時刻は変更しない。照合失敗でも価格収集は継続する。

```text
Bybit / Binance public trade klines
                |
                v
       independent ranking process
       | SQLite | frozen generation |
                |
       loopback read API (8769)
                |
       SvelteKit /api/rankings
                |
          /rankings page ------> one public TradingView Widget
```

元の銘柄名簿とランキングmapのversionを分ける。契約revisionごとに履歴を保存し、変更された参照契約の
履歴を連結しない。銘柄別の取得先はmapで固定する。通常の確定足はWebSocket、初期履歴と欠測はRESTを
使う。毎分の終了時刻Tから8秒後に入力を固定し、12秒の処理deadlineを超えた世代はAPIへ発行しない。
計算・保存・発行は重複起動しない。計算入力は3日分と価格境界を固定し、同じ世代の期間・HH:mm別の再計算で
後着足を混ぜない。

保存先は /home/tn/.local/share/prep-watchdeck-ranking が既定。SQLiteは4日と1分の確定足を保持し、
元stateと同一・内包関係の保存先を起動前に拒否する。公開HTTP接続に環境のproxyやDB接続設定を使わない。
通常の制限付き起動は /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/ranking/run-isolated.py を使う。
bubblewrapでhost filesystemをread-onlyにし、専用stateと一時領域だけを書込み可能にする。
新規unitはtemplateだけであり、既存installerの操作対象には追加していない。

外部RESTはcatalog取得と履歴workerを共通の上限で制御し、各Provider 2 request/秒・同時2接続とする。
WebSocketは全体6接続以内、再試行backoffは最大60秒、
補完queueはProviderごと2,000、対象参照は最大1,500、問い合わせcacheは世代ごと8件。
これらは上限であり、対応数や稼働受入の証明ではない。Browser数やHH:mmの変更で外部取得を増やさない。


順位変化のため、発行済みの現在世代と直前1世代の固定入力を保持する。過去世代の連鎖は保持せず、
各世代の条件cacheは8件以内。次世代を組み立てて公開する間だけ候補入力が加わる。
再起動後は現在のDBから新しい世代を発行し、初回の比較元はなしとする。
平常比・JST当日高安位置・過去日比較は、世代作成時のOHLC・quote turnoverから計算して固定する。
過去日比較に必要な初期履歴と保持期間を拡張し、指標を読むための追加REST、別Provider、
Widgetデータ取得は加えない。

## 保存1分足の品質補助lane

Market CoreのRecoveryは既存Postgresの現行契約と保存`candle_1m`を読み、UTC1分の完全な時間格子から
内部穴も検出する。手動CLIは既定でscanのみ。`PREP_WATCHDECK_CANDLE_RECOVERY_ENABLED`の既定はfalseで、
有効時だけMarket Service内の独立taskが起動時と15分境界で実行する。専用lock、HTTP件数・時間・
page上限を持ち、同じ版と定義hashを再確認して欠損行だけ挿入する。挿入時には既存artifactとmetricsの
更新を通知する。完了runは`collector_runs`と任意の`candle-recovery-state.json`へ記録する。
request予算を使った最後の対象の次から再開し、特定Venueの先頭へ処理が偏らない。
同じ有効化設定で、別taskが毎分native指標の現在・15分・1時間・24時間の不足endpointを確認する。
対象ごとにcutoffを再取得し、最大20 request・60秒・最低3秒間隔で公式履歴の実在足だけを
挿入する。専用lockと`candle-endpoint-recovery-state.json`を持ち、通常の履歴回復とは独立する。
過去日の遅着足は次のmaintenanceで確認済みParquetを再発行してからretention判定する。

Auditは手動の保存snapshot二つを固定copyして比較し、不変run directoryと最新indexを発行する。
Webの二つのGET routeは状態ファイルを検証して返すだけで、DB照会・再照合・Provider取得をしない。
OpenMarketは手動CLIでのみexact mappingを確かめて取得し、nativeの保存足へ書き戻さない。
Fixture Exportは1契約・1版・1窓をread-only repeatable-read DB transactionで固定し、任意の
Recovery/Auditファイルをtransaction後に別時刻として添付する。Ranking Coreへ値を書き込まない。

## 独立したAttention Core

`watchdeck-attention`は別processと専用SQLite WALを持つ。Marketの`service-state.json`を前後で照合して`universe-snapshot.json`と任意の`market-metrics.json`を固定し、Ranking loopbackの`15m / 00:00 JST / turnover / minTurnover=0`を1回読む。共通cutoffを捏造せず、inputごとの作成時刻・観測時刻・generation・map/metric versionを保存する。Market/Ranking writerとProvider clientを呼ばない。

毎分の計算結果を単一writerのtransactionとreadbackで確認してから、専用stateのimmutable JSONと`artifacts/current.json`へatomic公開する。全世代のcurrent responseとshadow allocationを保存し、特徴量・成分の評価用evidenceはRanking cutoffが5分境界の最初の1世代だけ保存する。失敗時は新しい世代を公開せず、APIで前世代の時刻を保ったstaleを返す。

Webはloopbackの`GET /attention`を`/api/attention`経由で読む。GETから再計算・入力取得・監視対象変更を行わない。Outcome settlementは明示的なoffline exportを使い、候補群評価は固定済みの候補と確定後の将来結果だけを読む。自動captureは接続していない。設計判断は[Decision 0015](../decisions/0015-attention-core.md)を参照する。

Discoveryも同じAttention writerが既存入力から毎分評価し、既存Attention SQLiteに最新raw projectionと条件episodeを持つ。
最新projectionは置換し、全件rawのimmutable履歴を追加しない。終了episodeだけを7日・最大10,000件に制限し、
active/interruptedは保持する。Attention世代とDiscoveryはそれぞれcommit/readback後に公開し、
後者の保存失敗は成功扱いせず`storage_unavailable`と観測中断を示す。
`GET /discovery`とWebの`/api/discovery`は読取だけで、Provider・user-workspace・selectionを呼ばない。
`/discovery-summary`はraw treeを含まない一覧で、Webの15秒pollは一覧と最大4対象の詳細だけを読む。
詳細はasset主キーのtableとmetadataを1 SQL snapshotで読み、全Universe JSONやjson_eachを走査しない。
旧full projectionを併存させ、旧writerによるrollback後も次回起動でindexを再構築する。
世代更新時も旧projectionは必要な継続判定fieldだけを読み、完全payloadのreadbackは保存bytesの一致で確認する。

Webは最大4件の比較pinを`user-workspace.json` v2、手動の監視/見送りを別の`manual-decisions.json`に保存する。
お気に入り、条件episode、比較候補、実captureのselectionは独立する。比較・判断記録だけではcaptureを変更せず、
実Venueの明示確認時に最新identityを再照合して既存selectionへ送る。新しい監視serviceや外部通知は追加しない。

## 研究readerとoffline比較

Market packageの独立`research` CLIは一契約/versionのread-only RR観測を別rootへ記録する。
Market/Ranking/Attention writerとprocess/stateを共有せず、注文やmanual selectionへ接続しない。
Payloadと公開後receiptを分け、固定rules/input/source hashでoffline比較する。
保存・時刻・有限口座と任意tool境界は[/home/tn/projects/prep-watchdeck/docs/current/research.md](research.md)、採用判断は
[/home/tn/projects/prep-watchdeck/docs/decisions/0016-reader-observed-research.md](../decisions/0016-reader-observed-research.md)を参照する。
