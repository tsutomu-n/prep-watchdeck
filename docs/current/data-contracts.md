# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書は現在productionの3 Venue Perp runtimeが実装しているdata contractを記述する。
現在のfield、Venue、artifact数、timeframe、retention等を将来の永久上限として扱わない。
製品境界は[`product-boundary.md`](product-boundary.md)を正本とする。

## 現行Identity

- `venueInstrumentId=<venue>:<sourceSymbol>`
- `venueInstrumentVersionId`はPostgres SCD2 versionの内部ID
- `groupId=crypto:<BASE>:linear-perp`
- `mappingMethod=exact_base_heuristic`は、active、crypto、linear perpetual、base完全一致、base数量、
  multiplier 1、Venue内候補1件をすべて確認した場合だけ設定する

現行Perp coreではalias、`1000X`、同一Venue衝突、quantity unit不明、HIP-3、RWA、synthetic/RFQを
自動group化しない。

これは現在のPerp auto-grouping contractであり、別asset-class surfaceや、明示的に検証されたmapping table、
新しいidentity schemeを将来禁止しない。symbol名だけから推測して同一視しない原則は維持する。

## 現行値と単位

- `markPrice`と`referencePrice`を分け、`referencePriceKind=index|oracle|none`を保持する
- Fundingはraw、interval、nextFundingを保存し、interval確認時だけper-hourを公開する
- OIはraw値とraw unitを保持し、確認できる時だけbase/notionalへ派生する
- 24h volumeはsource由来値とunitを保持する
- source timestampがない場合はnullを維持する

現行参考mark中央値以外でUSD/USDC/USDT parityを無条件に仮定しない。

将来のranking/feature engineeringでは、意味、unit、window、timestamp、identityを確認できるfeatureについて
正規化、集約、比較できる。比較不能な値を無理にscoreへ入れない。

## Storage truth

現行runtime:

- Postgres: current/recent catalog、identity、collector run、market state、candle、funding、selected data、manifest
- confirmed Parquet: retention後のnormalized history
- JSON artifact: Web用の再生成可能read model
- local files: selection control、Past Note等

現在のdataset名やstorage engineを将来永久固定しない。新しいasset class、ranking feature、model output、journal等は
必要に応じて別table/dataset/artifact/storage laneを持てる。

## 現行Parquet archive

`market_state_1m`、`candle_1m`、`funding_events`のnumeric列は現行Parquetで`Decimal(38,18)`を使う。
readback/digest/checksum確認前に対応するhistoryを削除しない。

このprecision、dataset集合、retention日数は現行runtimeのcontract。変更時はmigrationとreadback検証を行う。

## 現行JSON read model

現在は次のschemaを使う。

- `schemas/universe-snapshot.schema.json`
- `schemas/market-chart.schema.json`
- `schemas/selected-market.schema.json`
- `schemas/service-state.schema.json`

すべて現行`schemaVersion=1`。unknown property禁止、NaN/Infinity禁止、timestamp契約等は各schemaに従う。

**4 artifactだけに永久固定しない。** Ranking、model output、Stocks、portfolio、journal等は新artifact/schema/APIを
追加できる。

### universe-snapshot.json

現在のUniverse itemはidentity、Venue/source symbol、quote/settle/collateral、execution model、catalog provenance、
L1値、unit、freshness、collector run、payload hash、error、参考mark中央値等を持つ。

`quality=stale|unavailable`の値をfreshとして公開しない。

### market-chart.json

現在は1 selected `venueInstrumentId`と`5m|15m|1h|4h|24h`を持ち、各timeframe最大500 bars。
barはOHLC、volume、trade count、finality、source/observed時刻、complete、quality理由等を持つ。

**5 timeframe、500 bars、単一selected instrumentは現行実装値であり永久制約ではない。**
将来任意timeframe、長期履歴、indicator、comparison、multi-chart等へ拡張できる。

### selected-market.json

現在は1 active selectionまたはnull。group instruments、最大20 bids/asks、直近100 trades、
`$100/$500/$1,000` book walk等を持つ。

現在のschemaではbook walkに`includesFees=false`、`predictsFutureImpact=false`、
`confirmsOrderAvailability=false`を固定する。

**selection数、20段、100件、notional、fee/impact非対応は現行値。** 将来別schema/versionまたは別artifactで
可変値、確認済みfee、impact model等を追加できる。

### service-state.json

現行collector/artifactのfreshnessとwrite結果を持つ。Web process healthとmarket data qualityを混同しない。

## 現行Selection command

現在のWebは`control/selection.json`をlock付きatomic replaceする。

```json
{
  "schemaVersion": 1,
  "groupId": "crypto:BTC:linear-perp",
  "venueInstrumentId": "bitget:BTCUSDT",
  "requestedAt": "2026-08-14T00:00:00.000Z",
  "heartbeatAt": "2026-08-14T00:00:00.000Z"
}
```

現行validationはactive grouped instrument、timestamp、expiry等をfail-closedに確認する。
将来、単独instrument、複数selection、pinned/watch queue等の別command contractを追加できる。

## 現行Past Note

`past-notes/<venueInstrumentId>.json`に観測annotationを保存する。現在は60日後にread時pruneし、同じ
`venueInstrumentId + reason`は置換する。

60日は現行policy。Decision Memo、Trade Journal、review workflowは別data modelとして追加できる。

## 現行Web API

| method | path | 現行contract |
| --- | --- | --- |
| GET | `/api/market-data` | 現行artifact bundle、`no-store` |
| POST | `/api/selection` | 現在はlocalhost限定でselection write |
| GET | `/api/market-past-notes?venueInstrumentId=...` | Past Note読取 |
| POST | `/api/market-past-notes` | 現在はlocalhost限定で保存 |
| GET | `/api/health` | Web process health |

localhost限定、route数、bundle構成は現行runtime値。将来remote accessや新surfaceを追加できるが、authentication、
authorization、CSRF、secret、conflict等をその変更で設計する。

## 拡張時の原則

- `未実装`を`禁止`としてschemaへ焼き付けない。
- 既存schemaを無理に全asset classへ拡張せず、必要なら新しいbounded context/schemaを作る。
- backward compatibilityが必要ならversionを上げ、reader/writer移行を明示する。
- data quality、unit、identity、timestamp、provenanceを新featureでも維持する。
- ranking/model outputのsource dataとcalculation versionを追跡可能にする。
