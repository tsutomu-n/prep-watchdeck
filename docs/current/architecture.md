# prep-watchdeck 現行アーキテクチャ

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書はRepositoryの現行実装を記述する。稼働中の配置versionは運用記録とunitから別に確認する。
現在のprocess数、DB、artifact数、poll周期、selection数等を将来のWatchdeck全体へ永久固定しない。
製品境界は[`product-boundary.md`](product-boundary.md)を正本とする。

## 現行Process境界

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

- `prep-watchdeck-market-db.service`は現在の専用Compose project/DBを所有する。
- `prep-watchdeck-market.service`は現在catalog、L1、candle、selected stream、DB write、artifact発行を1 processで行う。
- 現行WebはJSON read modelを読み、Postgresへ直接接続しない。
- maintenance timerはFunding sync、archive/readback/retentionを実行する。

このprocess topologyは現行runtimeの安全なbaseline。将来のranking worker、Stocks core、model service、追加artifact、
remote API等を必要に応じて別process/bounded contextとして追加できる。

他projectのDB/container/stateを共有しない原則は維持する。

## 現行Collector lane

### Catalog / Identity

Catalogは現在15分周期でVenue別に取得し、成功sourceをSCD2保存する。source kind、endpoint、payload hash、
observed/source time、capability、exclusion reasonを保持する。

現行auto-groupはactive crypto linear perpetual、base完全一致、base数量、multiplier 1、Venue内候補1件を要求する。
条件外instrumentを推測でgroupへ入れない。

将来の別asset classやexplicit mappingは別contractで追加できる。

### L1

現在は60秒grid、single-flight、Venue fetch deadlineを持ち、一部Venue障害を他Venueへ波及させない。
前周期値をfreshとして再利用しない。

周期/deadlineは現行capacity値で変更可能。

### Candle

現在は3 Venueからfinished/confirmed/derived-final 1分足を収集し、queue/batch writerでPostgresへ保存する。
version境界、unknown version、invalid barを安全側に拒否し、gapを捏造補間しない。

将来、別timeframe/source/backfill laneを追加できる。

### Settled Funding

現在のmaintenanceは3 Venueのsettled fundingを同期する。現在値/estimatedとsettled historyを区別し、version boundary、
idempotency、conflictを検証する。

48時間catch-up等は現行runtime値。より深いhistorical laneを別設計で追加できる。

### Selected market

現在Webはselection commandをlocal fileへatomic writeし、market serviceが1 groupを購読する。
現行値は500ms debounce、15分TTL、5分heartbeat、旧subscription cleanup、CLOB depth/trade等。

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

現在はstate rootの`artifacts/`へ4 JSONを同一filesystem内でatomic publishする。

- `universe-snapshot.json`
- `market-chart.json`
- `selected-market.json`
- `service-state.json`

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
Hyperliquidは`candleSnapshot`、Asterは`klines`を使う。日足はUTC 00:00開始へ揃え、
Bitgetでは`1Dutc`を指定する。Webへ取引所の秘密API keyを追加しない。

1ページ最大500本、server cacheは30秒・32件、同時取得は8件までで同じ要求をまとめる。
BitgetへのHTTP開始間隔はWeb process内で全銘柄・時間足共通の1秒以上とする。
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
通常の制限付き起動は /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/ranking/run-isolated.py を使う。
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
