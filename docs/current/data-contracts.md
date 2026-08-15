# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-15T11:04:37+09:00`
- 検証: `2026-08-15T11:04:37+09:00`
- 状態: `現行`

---

## Identity

- `venueInstrumentId=<venue>:<sourceSymbol>`。例: `bitget:BTCUSDT`。
- `venueInstrumentVersionId`はPostgres SCD2 versionの内部ID。
- `groupId=crypto:<BASE>:linear-perp`。
- `mappingMethod=exact_base_heuristic`は、active、crypto、linear perpetual、base完全一致、
  base数量、multiplier 1、Venue内候補1件をすべて確認した場合だけ設定する。

alias、`1000X`、同一Venue衝突、quantity unit不明、HIP-3、RWA、synthetic/RFQは自動group化しない。

## 値と単位

- `markPrice`と`referencePrice`を分け、`referencePriceKind=index|oracle|none`を保持する。
- Hyperliquid oracleをindexと表示しない。
- Fundingは`fundingRateRaw`、`fundingIntervalSeconds`、`nextFundingAt`を保存する。
  周期確認時だけ`fundingRatePerHour`を公開する。
- OIは`openInterestRaw`と`openInterestRawUnit`を常に由来どおり保持する。base数量を確認できる時だけ
  `openInterestBase`、markと両方が有効な時だけ`openInterestNotional`を算出する。
- 24時間出来高は`volume24hRaw`と`volume24hUnit`をVenue別に表示し、時間窓の差分率を作らない。
- `sourceAt`が配信されないsourceではnullを維持し、`observedAt`で鮮度を判定する。

USD、USDC、USDTのparity仮定は参考mark中央値だけに適用する。Venue値を変換・合算・rankingせず、
実行可能価格として扱わない。

## JSON read model

正本schemaは次の4 file。すべて`schemaVersion=1`、unknown property禁止、NaN/Infinity禁止、
ISO 8601 UTC timestampを使う。

- `schemas/universe-snapshot.schema.json`
- `schemas/market-chart.schema.json`
- `schemas/selected-market.schema.json`
- `schemas/service-state.schema.json`

Python Pydantic modelからschemaを検証し、Web typeは`bun run generate:types`で生成する。
生成済み`.d.ts`を手編集しない。

### universe-snapshot.json

Top-levelは`generatedAt`、`status`、`qualityReasons`、`parityAssumption`、`items`。
各itemはidentity、Venue/source symbol、quote/settle/collateral、execution model、catalog provenance、
L1値、単位、freshness、collector run、source payload hash、error code、参考mark中央値を持つ。

`quality=stale|unavailable`の値をfreshとして公開しない。参考中央値は同一group、同一cycle、
2 Venue以上、age 120秒以内、skew 30秒以内、USD-like quote/settle/collateralをすべて満たす時だけ
`ready`にする。24時間出来高の中央値は作らない。

### market-chart.json

Top-levelは`venueInstrumentId`と`timeframes`。timeframeは`5m|15m|1h|4h|24h`、各最大500 bars。
barはOHLC、base/notional volume、trade count、`confirmed|derived_final`、source/observed時刻、
source bar数、complete、quality理由を持つ。version境界を跨ぐbar、欠落barを補間しない。

### selected-market.json

1 active selectionまたはnullを持つ。selectionには`selectionId`、`groupId`、
`primaryVenueInstrumentId`、`expiresAt`、group instruments、直近100 tradesを含む。
各instrumentは最大20 bids/asks、depth時刻/age、quality、$100/$500/$1,000 book walkを持つ。

depthが10秒超、板不足、非USD-like、非CLOB、単位不明なら概算をnullにし理由を返す。
`includesFees=false`、`predictsFutureImpact=false`、`confirmsOrderAvailability=false`を固定する。

### service-state.json

catalog/L1の最新collector run、freshness、artifactごとのwrite結果を持つ。`ready`以外でも
取得できたstatusと理由を残す。Web healthとmarket data qualityは別契約であり、HTTP 200だけを
market data readyの証拠にしない。

## Selection command

Webは`control/selection.json`をlock付きatomic replaceする。

```json
{
  "schemaVersion": 1,
  "groupId": "crypto:BTC:linear-perp",
  "venueInstrumentId": "bitget:BTCUSDT",
  "requestedAt": "2026-08-14T00:00:00.000Z",
  "heartbeatAt": "2026-08-14T00:00:00.000Z"
}
```

選択identityが同じheartbeatでは`requestedAt`を維持する。Universeのactive grouped instrumentで
ないcommand、不正timestamp、future revision、期限切れcommandはfail-closedに無視する。

## Past Note

`past-notes/<venueInstrumentId>.json`にschema version 1、`venueInstrumentId`、notesを保存する。
noteはreason、本文、`observedAt`、`expiresAt`を持ち、60日後に読取時pruneする。
reasonが空なら`過去注記`を保存する。同じ`venueInstrumentId + reason`で再保存した場合は、既存noteを
新しいnoteで置き換える。
旧Bitget symbol noteをheuristic groupへ自動移行しない。

## Web API

| method | path | contract |
| --- | --- | --- |
| GET | `/api/market-data` | 4 artifactのschema検証済みbundle、`no-store` |
| POST | `/api/selection` | localhost限定。group/primaryをatomic write |
| GET | `/api/market-past-notes?venueInstrumentId=...` | instrument note読取 |
| POST | `/api/market-past-notes` | localhost限定。instrument note保存 |
| GET | `/api/health` | Web process health。market qualityとは別 |

不正JSON、schema不一致、missing fileは推測で補完せず503、unavailable、または空stateとして扱う。
