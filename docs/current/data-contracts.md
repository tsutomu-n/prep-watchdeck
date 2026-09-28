# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-12T09:03:01+09:00`
- 検証: `2026-09-12T09:57:08+09:00`
- 状態: `現行`

---

## Identity

- `venueInstrumentId=<venue>:<sourceSymbol>`。例: `bitget:BTCUSDT`。
- `venueInstrumentVersionId`はPostgres SCD2 versionの内部ID。
- `groupId=crypto:<BASE>:linear-perp`。
- `mappingMethod=exact_base_heuristic`は、active、crypto、linear perpetual、base完全一致、
  base数量、multiplier 1、Venue内候補1件をすべて確認した場合だけ設定する。

alias、`1000X`、同一Venue衝突、quantity unit不明、HIP-3、RWA、synthetic/RFQは自動group化しない。

Asterは`underlyingType=COIN`に加えて、`underlyingSubType`が空配列、または`AI`、`Meme`、
`STORAGE`、`Top`だけで構成される場合にcryptoとして採用する。field欠落、型不正、未知tag、
`STOCK`、`ETF`、`Commodities`、`pre-launch`を含む行は`rwa_or_unconfirmed`として除外する。
新しいtagをsymbol名から推測して採用しない。

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

## Parquet archive

`market_state_1m`、`candle_1m`、`funding_events`のnumeric列は、Parquetで
`Decimal(38,18)`へ固定する。入力値がこの型で可逆表現できずsource row digestとreadback row digestが
一致しない場合はmanifestをconfirmしない。行順からdecimal scaleを推測せず、丸めた値を履歴正本にしない。

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
このartifactはcollectorの1分足集約であり、画面の長期Chartが読むnative履歴APIとは別の契約である。

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
| GET | `/api/chart-history?instrument=<id>&timeframe=<tf>&before=<ISO UTC>` | 選択Venueのnative足。`before`省略時は最新ページ、指定時はその時刻より前 |
| GET | `/api/price-change?instrument=<id>&referenceTime=<HH:mm>` | 指定したJST時刻直前の確定1分足終値からの約定騰落率 |
| POST | `/api/selection` | localhost限定。group/primaryをatomic write |
| GET | `/api/market-past-notes?venueInstrumentId=...` | instrument note読取 |
| POST | `/api/market-past-notes` | localhost限定。instrument note保存 |
| GET | `/api/health` | Web process health。market qualityとは別 |

不正JSON、schema不一致、missing fileは推測で補完せず503、unavailable、または空stateとして扱う。

### Chart履歴API

`timeframe`は`5m|15m|1h|4h|24h`。UIでは`24h`を`1D`と表示し、1本が1日であることを示す。
`before`は排他的なISO 8601 UTC時刻で、未来時刻、重複・未知query parameterは400になる。
銘柄はfreshな検証済みUniverseのactive grouped linear perpetualだけから解決する。
利用者から任意URL、独立したsource symbol、credentialを受け取らない。

応答は`venueInstrumentId`、`timeframe`、`generatedAt`、`bars`、`hasMore`、`nextBefore`。
各barは`bucketAt`、OHLC、`volumeBase`、`volumeNotional`、`complete`を持つ。
`bucketAt`はUTCの足開始時刻で、OHLCは有限・正値・高安関係を検証し、出来高不明はnullを保つ。
`complete`は足の時間枠が経過したことだけを表し、取引所の確定通知やcollectorのfinalityとは異なる。
native履歴は取引所が当該symbolへ配信した履歴であり、collectorのSCD2 version履歴を再構成しない。

各ページは昇順・時刻重複なしで最大500本。不一致の重複やUTC枠外の足を推測で補正しない。
非空ページは`hasMore=true`と最古足の`nextBefore`を返し、次ページを要求できる。
500本未満でも欠損と履歴の終端を同一視しない。空ページは`false` / `null`で終了する。
失敗時は非200と限定された`error` codeを返す。期限切れcacheを成功応答にしない。

### 約定騰落率API

`instrument`と`referenceTime`を各1件必須とし、未知・重複parameter、不正なHH:mmは400。
`referenceTime`はJST固定の00:00〜23:59。server時刻以前の直近の指定時刻を`baselineAt`とし、
その60秒前に始まる1分足の終値を`baselinePrice`とする。基準足は当該時刻との完全一致と時間枠の
終了を必要とし、欠落を古い足や次の足で代替しない。

`currentPrice`も同じVenue・契約の1分足closeで、進行中の足を含む。`currentCandleAt`は足開始UTC、
`generatedAt`は最新価格を実際に取得した時刻。基準cacheを再利用しても取得時刻を更新した扱いにしない。
最新価格のcache・取得中要求は取得開始分を区別し、基準時刻前の要求を新しい基準へ共有しない。
最新足の開始から120秒を超えた場合は`latest_stale`。価格は有限・正値で、
`changePercent = (currentPrice / baselinePrice - 1) * 100`を返す。Markや参考中央値とは独立する。

応答は`venueInstrumentId`、`venueInstrumentVersionId`、`referenceTime`、`baselineAt`、`generatedAt`、
`status`、`reason`、`baselinePrice`、`currentPrice`、`currentCandleAt`、`changePercent`。
`status=unavailable`では`changePercent=null`とし、`baseline_missing`、`latest_missing`、
`latest_stale`で不足を区別する。HTTP取得・応答検証の失敗は非200と限定したerror codeにする。
freshな検証済みUniverseのactive grouped linear perpetualだけを解決し、cacheも契約version・
quote・settleを区別する。HTTP応答は`no-store`で、任意URLや独立symbolは受け取らない。

## 独立ランキングの契約

/home/tn/projects/prep-watchdeck/schemas/ranking-map.schema.json と
/home/tn/projects/prep-watchdeck/schemas/ranking-response.schema.json は既存4 artifactと独立している。
Pythonの検証modelを正本とし、/home/tn/projects/prep-watchdeck/scripts/ranking/generate-schema.py で生成する。
Web型は既存の `bun run generate:types` に含む。

mapは元の全instrument ID・version、名簿fingerprint・確認時刻、共通row ID、元Venue、
原資産・数量倍率、固定参照のProvider・symbol・quote/settle・perpetual種別・revision、
Widgetの別symbolと根拠を持つ。`verified / unsupported / review / out_of_scope`を区別する。
`review`を対応済みとして価格取得せず、異なる原資産や数量を名前だけで結合しない。
Widget symbolは独立に照合し、参照契約keyへ結び付ける。

全行のTは同じUTC分境界。C(t)はtで終了する確定1分足の約定終値で、Mark・Indexは代入しない。
15分・1時間は `(C(T)/C(T-w)-1)*100`、JST HH:mmはT以下で最後に到来した基準Aから
`(C(T)/C(A)-1)*100`を計算する。売買代金は `[T-w,T)` または `[A,T)` の確定足のquote turnover合計。
Binanceはklineのquote asset volume、Bybitはturnoverを用いる。原資産数量に終値を掛けた推計や
24時間出来高の差分は用いない。全て当該参照契約のUSDT建てであり、Venue横断合算や通貨parityを含まない。

価格境界と期間内売買代金の全てがそろう行だけを順位候補とする。上昇率は正の値を降順、下落率は
負の値を昇順、売買代金は降順。表示丸め前に比較し、同値はrow IDの昇順。下限はUSDTで両指標へ共通適用。
0%は上昇・下落順位へ含めず、売買代金順では比較する。提供元の実0は保持し、欠測を0で補わない。
T=Aは`starting`とし、順位を作らない。

`GET /api/rankings?period=15m&dailyReferenceJst=00:00&order=gainers&minTurnover=0` は
独立APIの同一世代だけを返す。期間は`15m / 1h / daily`、順序は`gainers / losers / turnover`。
応答はgeneration ID、map/metric version、T・A・生成時刻、件数と除外理由、全行を含む。
`history_missing / source_delayed / source_unavailable / reference_invalid / invalid_data` と、
mapの要確認・未対応・対象外、下限未満・方向対象外を分ける。最新Tから150秒を超えた結果は`stale`、
名簿確認から24時間を超えた状態は`rosterStale`。古い値の時刻を新しく付け替えない。
専用API未起動・初回世代待ち・不正な応答はWebで503、問い合わせ不正は400にする。
