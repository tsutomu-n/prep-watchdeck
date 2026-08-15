# prep-watchdeck 現行アーキテクチャ

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-15T03:18:13+09:00`
- 検証: `2026-08-15T03:18:13+09:00`
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
- `prep-watchdeck-market-maintenance.timer`は毎時archive/readback/retentionを起動し、各dataset/Venueの
  最古未archive日から最大3日と指定日を処理して停止期間を段階的にcatch-upする。

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

現行collectorは`funding_events`のproducerを持たない。funding値は`market_state_1m`に保持する。
`funding_events`はtableとarchive/retentionのcontractだけが存在し、同tableが空であることを
収集失敗として扱わない。

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
