# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 検証: `2026-09-16T19:56:52+09:00`
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

## 独立ランキングの契約

/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/schemas/ranking-map.schema.json と
/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/schemas/ranking-response.schema.json は既存4 artifactと独立している。
Pythonの検証modelを正本とし、/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/generate-schema.py で生成する。
Web型は既存の `bun run generate:types` に含む。

mapは元の全instrument ID・version、名簿fingerprint・確認時刻、共通row ID、元Venue、
原資産・数量倍率、固定参照のProvider・symbol・quote/settle・perpetual種別・revision、
Widgetの別symbolと根拠を持つ。`verified / unsupported / review / out_of_scope`を区別する。
`review`を対応済みとして価格取得せず、異なる原資産や数量を名前だけで結合しない。
`ranking-map-v2`の行statusと`ranking-v2`応答の`mappingStatus`は、元の原資産同一性と
固定参照契約の採用資格を表す。元契約の`originals[].multiplier=null`は数量換算未確認であり、
確認済み参照契約によるランキングを止めない。元数量を使う換算には利用できない。
Widget symbolは独立に照合し、参照契約keyへ結び付ける。Widgetの`review`はChartだけを停止する。
`--require-ranking-qualified`は行の`review`が0であることを要求する。
旧`--require-reviewed`は行・元数量倍率・Widgetの全確認を要求するgateとして保持する。
`unsupported`は採用範囲で対応不可と確認した理由を保持し、同一性・参照の根拠が不足する
`review`を置き換えるために使わない。数量倍率の未確認を`unsupported`へ変更しない。
参照APIへ対応した行でWidgetを`unsupported`と確定する場合も、理由と根拠を必須とする。

証拠台帳の`remaining`は行の要確認、`quantityUnverified`は元instrument単位の数量未確認を保持する。
元倍率nullの行を採用する場合は、`rankingQualification`へ元ID集合・固定参照key・identity根拠・
参照根拠を記録する。checkerは欠落・重複・不一致を拒否する。報告は`rankingQualified`、
`quantityQualified`、`widgetQualified`を分け、全て確認済みの場合だけ`qualificationComplete=true`。
旧map/APIのv1を自動変換せず、明示的な再審査・再生成を要する。map digestはschema世代も含み、
新旧mapの順位差は比較不可となる。SQLite形式・metricVersion・計算式はこの改訂では変更しない。

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


### 順位比較と追加指標

`metricVersion`は`trade-close-quote-turnover-analysis-v2`。応答の`previousGenerationId`と
`previousCutoff`は比較元として保持した発行済み世代を示す。現在Tに対してT−60,000msの世代を、
同じmap/metric version、期間、順序、下限、JST HH:mmで再計算する。JST可変期間の基準日時が
切り替わる世代間は比較しない。初回とprocess再起動では比較元を持たず、保存済みsnapshotや
後から取得した足で過去の発行結果を復元しない。

各行の`rankChange`は`status / previousRank / delta / reason`を持つ。`compared`のdeltaは
前順位−現順位、`new`は前回だけ順位外、`not_ranked`は現在順位外、`unavailable`は比較不可。
比較元の欠落を`new`へ変換しない。今回または前回のTが現在から150秒を超えた場合は比較不可にし、
Webも取得停止時のclockで無効化する。過去世代の入力は後着訂正で変えない。

`turnoverRatio`と`dayRangePosition`はそれぞれ独立した`value / status`を持ち、既存の行stateや
順位適格性へ追加指標の欠測を混ぜない。値は全行と選択詳細で同じ世代から読む。

- 平常比: Tの直近24時間を15分または1時間の非重複窓へ分割する。最新窓Q0を除いた95窓/23窓の
  中央値Bに対するQ0/B。quote turnoverはUSDT建ての当該参照契約で、数量倍率を再乗算しない。
  24時間内の足が1本でも欠ければ`history_missing`、B=0は`no_baseline`、JST可変期間は
  `unsupported_period`。古い境界の終値C(T−24h)は売買代金指標の必要条件ではない。
- 当日位置: DをTの属するJST日の00:00とし、[D,T)の確定足の最大high H・最小low Lと終値C(T)から
  `100*(C(T)−L)/(H−L)`を算出する。Dで終了する足は前日分なので含めない。T=Dは`starting`、
  H=Lは`no_range`、途中足または最終足の欠落は`history_missing`、完全な入力のOHLC不整合や
  範囲外の数値は`invalid_data`とし、0〜100への丸め込みで隠さない。

high/lowと売買代金は世代作成時にSQLiteから一度読み、指標を固定する。Web/APIの読取り時には
DBを再参照しない。SQLiteの表・保存期間は変更せず、指標は保存済みOHLCにも適用できる。
