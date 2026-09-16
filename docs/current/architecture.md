# prep-watchdeck 現行アーキテクチャ

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-12T21:37:19+09:00`
- 検証: `2026-09-12T09:57:08+09:00`
- 状態: `現行`

---

## Process境界

```text
Bitget / Hyperliquid Core / Aster public API
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

- `prep-watchdeck-market-db.service`は専用Compose projectとloopback port 55432だけを所有する。
- `prep-watchdeck-market.service`はcatalog、L1、candle、selected stream、DB write、artifact発行を
  1 processで行う。file lockで同一state rootのcollector重複起動を拒否する。
- `prep-watchdeck-web.service`はJSON read modelだけを読む。Postgresへ接続しない。
- `prep-watchdeck-market-maintenance.timer`は毎時、精算済みFundingの同期後に
  archive/readback/retentionを起動する。各dataset/Venueの最古未archive日から最大3日と指定日を
  処理して停止期間を段階的にcatch-upする。

JustPassのPostgres、port 5432、container、volume、database、roleは共有しない。

## Collector lane

### Catalogとidentity

Catalogは15分周期で全Venueを独立取得する。成功したVenueだけをPostgresへSCD2保存し、
DB commit成功後にin-memory catalogを入れ替える。source kind、endpoint、payload hash、観測時刻、
source時刻、capability、除外理由を保持する。

自動group条件はactive crypto linear perpetual、base完全一致、base数量、multiplier 1、
Venue内候補1件である。条件を満たさないinstrumentは自動groupへ含めない。

### L1

L1は60秒gridのfixed-rate single-flight。Venue fetch上限20秒、cycle deadline 50秒で、
一部Venue障害は他Venueを停止させない。前周期値をfreshとして再利用せず、missing instrumentは
そのcycleで`unavailable`として保存する。

### Candle

- Bitget: finished 1分足RESTを120秒ごとに分散取得し、直近3本をdedupeする。
- Hyperliquid: 1 WebSocketから足終了5秒後の最終値を`derived_final`として保存する。
- Aster: sharded WebSocketのkline `x=true`だけを`confirmed`として保存する。

Candle queueは20,000、flushは最大250件または1秒、DB writerは1接続。instrument version境界を
跨ぐbar、version不明、複数versionへ一致するbarはbatchごと拒否する。gapは補間しない。

### Settled Funding

毎時maintenanceの`funding-sync`は3 Venueの公開履歴endpointを独立取得し、現在有効なCatalog versionの
開始時刻以後、かつ最大48時間の範囲にある精算済みeventだけを`funding_events`へ保存する。現在値や
推定値は履歴へ入れない。同じinstrument version・精算時刻・rateは冪等、同じkeyでrateが異なる場合は
transactionをrollbackする。周期不明時は1時間換算を作らず、1 Venueの失敗で他Venueの成功分を失わない。

### Selected group

Webは`control/selection.json`をatomic writeする。market serviceはlast-write-wins、500ms debounce、
15分TTL、5分heartbeatで1 groupだけを購読する。primary変更時は旧taskをclose/awaitしてから
新taskを開始し、旧subscriptionを10秒以内に解除する。

選択groupの各CLOB instrumentだけ、最大20段とtradesを正規化する。catalog fingerprintを再確認し、
primary消失、group membership変更、non-CLOB、非linear、非USD-like、単位不明はfail-closedにする。

## Storage truth

- Postgres: current catalog、SCD2、identity、collector run、ephemeral raw market、直近L1/candle/funding、
  selected lease/depth/trade/raw、archive manifest。
- Parquet: confirmed後の`market_state_1m`、`candle_1m`、存在する`funding_events`。
- JSON: Web用の再生成可能read model。正本DBの代わりに書き戻さない。
- Past Note: `venueInstrumentId`単位のlocal annotation。market dataではない。

現在値と推定値は`market_state_1m`に保持し、精算済み履歴だけを`funding_events`に保持する。
`funding_events`も容量sampleとarchive/retentionの必須対象であり、空を成功値0として扱わない。

Parquetは`dataset=<type>/venue=<venue>/date=YYYY-MM-DD/generation=<n>/part-0000.parquet`へ
ZSTDで書く。row count、unique key、timestamp、row digest、file SHA-256をreadbackし、manifestを
confirmしてからだけ対応するnormalized期限切れ行を削除する。最新generationと直近3 superseded
fileを残す。

`raw_market_observations`とselected raw/historyはParquet履歴正本の対象外としたephemeral dataである。
rawは7日+2時間、selected normalized/historyは8日のage条件を満たしてからbounded deleteする。

## Artifact lane

`~/.local/share/prep-watchdeck-market/artifacts/`へ次を同一filesystem内でfsync後atomic replaceする。

- `universe-snapshot.json`
- `market-chart.json`
- `selected-market.json`
- `service-state.json`

Webは各schemaをAjvで検証し、不正fileを部分的に推測せずunavailableとして扱う。

## State境界

標準rootは`PREP_WATCHDECK_MARKET_STATE_DIR`、未指定時は
`~/.local/share/prep-watchdeck-market`。Postgres、archive、artifact、control、Past Note、serviceと
maintenanceのlockを
このrootへ置く。E2E、smoke、shadowは別のstate root、DB、Web portへ隔離する。

旧DuckDB stateと旧unit backupはrollback用であり、新serviceから読まない。cutover承認前に
旧runtimeを停止・削除・上書きしない。

## 独立したデイトレランキング

/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/ は、Bybit・Binanceの公開USDT perpetualを
別processで継続取得する。元の3 Venueから価格・売買代金を補完しない。既存artifactからは
名簿作成時にidentityだけを抽出し、確認済みmapとして保存する。通常収集は保存済みmapで動作し、
元のcollector、4 artifact bundleの鮮度、Postgres、Parquet、Selection、Past Noteへ依存しない。

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
計算・保存・発行は重複起動しない。計算入力は24時間分を固定し、同じ世代の期間・HH:mm別の再計算で
後着足を混ぜない。

保存先は /home/tn/.local/share/prep-watchdeck-ranking が既定。SQLiteは最大48時間の確定足を保持し、
元stateと同一・内包関係の保存先を起動前に拒否する。公開HTTP接続に環境のproxyやDB接続設定を使わない。
通常の制限付き起動は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/run-isolated.py を使う。
bubblewrapでhost filesystemをread-onlyにし、専用stateと一時領域だけを書込み可能にする。
新規unitはtemplateだけであり、既存installerの操作対象には追加していない。

外部RESTはcatalog取得と履歴workerを共通の上限で制御し、各Provider 2 request/秒・同時2接続とする。
WebSocketは全体6接続以内、再試行backoffは最大60秒、
補完queueはProviderごと2,000、対象参照は最大1,500、問い合わせcacheは世代ごと32件。
これらは上限であり、対応数や稼働受入の証明ではない。Browser数やHH:mmの変更で外部取得を増やさない。


順位変化のため、発行済みの現在世代と直前1世代の固定入力を保持する。過去世代の連鎖は保持せず、
各世代の条件cacheは32件以内。次世代を組み立てて公開する間だけ候補入力が加わる。
再起動後は現在のDBから新しい世代を発行し、初回の比較元はなしとする。
平常比とJST当日高安位置は、世代作成時のOHLC・quote turnoverから計算して固定し、
指標を読むための追加REST、保存期間拡大、別Provider、Widgetデータ取得は加えない。
