# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
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
| GET | `/api/chart-history?instrument=<id>&timeframe=<tf>&before=<ISO UTC>` | 選択Venueのnative足。beforeは排他的 |
| GET | `/api/price-change?instrument=<id>&referenceTime=<HH:mm>` | 指定JST時刻基準の約定騰落率 |
| GET | `/api/rankings` | 固定参照の独立ランキング。下記の期間・方向・下限で問い合わせ |
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

/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/schemas/ranking-map.schema.json と
/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/schemas/ranking-response.schema.json は既存4 artifactと独立している。
Pythonの検証modelを正本とし、/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/ranking/generate-schema.py で生成する。
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
