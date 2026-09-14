# prep-watchdeck 現行アーキテクチャ

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書は現在productionの3 Venue Perp runtime architectureを記述する。
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
