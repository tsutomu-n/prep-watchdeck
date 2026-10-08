# prep-watchdeck 現行データ契約

timestamp="2026-10-09(金)_00:39 JST"
- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-10-09T00:39:16+09:00`
- 検証: `2026-10-08T16:04:27+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書はRepositoryの3 Venue Perp実装のdata contractを記述する。稼働releaseの版と反映状況は別に確認する。
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

Catalogの完全なraw payloadと版のdefinition hashは保全する。Bitgetの公式定義における
`maxOrderQty`、`maxMarketOrderQty`、`posLimit`だけの変更では、価格・数量・上場identityが
変わらないため既存version/hash/開始時刻を維持する。Asterの`PERPETUAL`で正整数の
`onboardDate`がある場合は、その上場境界を保持したままextra metadataの`createTime`だけの
変動も版を分けない。`onboardDate`の変更、不在・不正な上場境界、その他のraw項目、normalized field、
上場lifecycleの変更は従来どおり版を分ける。既存版のhashや過去の保存足を書き換えず、
新しい完全なcatalog原文は別raw payloadとして記録する。

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

基幹4 artifactは次のschemaを使う。任意のnative metrics/activityは別契約として下記に記す。

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
| GET | `/api/native-activity` | Bitget短時間activityの任意artifact。schema・意味整合性を検証し、未生成・不正は503 |
| GET | `/api/chart-history?instrument=<id>&timeframe=<tf>&before=<ISO UTC>` | 選択Venueのnative足。beforeは排他的 |
| GET | `/api/price-change?instrument=<id>&referenceTime=<HH:mm>` | 指定JST時刻基準の約定騰落率 |
| GET | `/api/rankings` | 固定参照の独立ランキング。下記の期間・方向・下限で問い合わせ |
| POST | `/api/selection` | 許可済みlocal / Tailscale接続でselection write |
| GET | `/api/market-past-notes?venueInstrumentId=...` | Past Note読取 |
| POST | `/api/market-past-notes` | 許可済みlocal / Tailscale接続で保存 |
| GET | `/api/health` | Web process health |

local APIの接続判定はloopbackを要求する。外部hostnameは既定では拒否し、
`PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN`に明示したHTTPS originのhostnameとportに一致し、
Tailscale Serveが付与した`Tailscale-User-Login`があるloopback proxy requestを追加で許可する。
Serveは受信したidentity headerを除去して認証済みidentityを付与するため、backendをloopbackに限定し、
既存tailnet ACLを接続権限の境界とする。

タグ付き自端末にはuser identity headerがない。identityなしの例外は、proxyのHTTPS・Hostが設定authorityと
一致し、単一のforwarded IPがlocal tailscaledのRunning状態のタグ付きSelf IPであり、Self DNSが設定host、
WhoIs Node StableIDがSelf IDと一致する場合だけに限定する。local APIの取得は固定Unix socketへのread-only
requestで、時間・responseサイズを制限する。別端末、検証失敗、Funnelは拒否し、既存ACLを変更しない。
接続判定は非同期であり、各routeは認証結果をawaitしてから読取・更新へ進む。
JSON writeはさらにブラウザーのOriginが設定したHTTPS originと完全一致することを要求する。
TLS終端後のbackend HTTP originやcross-originのwriteは拒否し、localhostの既存判定も維持する。

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
freshな検証済みUniverseのactive linear perpetualだけを解決し、cacheも契約version・
quote・settleを区別する。HTTP応答は`no-store`で、任意URLや独立symbolは受け取らない。

## 独立ランキングの契約

[`ranking-map.schema.json`](../../schemas/ranking-map.schema.json)と
[`ranking-response.schema.json`](../../schemas/ranking-response.schema.json)は既存4 artifactと独立している。
Pythonの検証modelを正本とし、[`generate-schema.py`](../../scripts/ranking/generate-schema.py)で生成する。
Web型は既存の `bun run generate:types` に含む。

mapは元の全instrument ID・version、名簿fingerprint・確認時刻、共通row ID、元Venue、
原資産・数量倍率、固定参照のProvider・symbol・quote/settle・perpetual種別・revision、
Widgetの別symbolと根拠を持つ。`verified / unsupported / review / out_of_scope`を区別する。
`review`を対応済みとして価格取得せず、異なる原資産や数量を名前だけで結合しない。
`ranking-map-v2`の行statusと`ranking-v5`応答の`mappingStatus`は、元の原資産同一性と
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
独立APIの同一世代だけを返す。期間は`15m / 1h / 24h / daily`、順序は`gainers / losers / turnover`。
応答はgeneration ID、map/metric version、T・A・生成時刻、件数と除外理由、全行を含む。
`history_missing / source_delayed / source_unavailable / reference_invalid / invalid_data` と、
mapの要確認・未対応・対象外、下限未満・方向対象外を分ける。最新Tから150秒を超えた結果は`stale`、
名簿の照合が失敗した状態や確認期限を超えた状態は`rosterStale`。
`rosterGeneratedAt`は審査済みsnapshotの時刻、または完全なcatalog取得と全identity/version一致を
確認した最新catalogの観測時刻。後者はmapの`verifiedAt`や参照revisionを更新しない。
必須の`rosterHealth`は`status`、`catalogObservedAt`、`sourceInstruments`、
`addedInstrumentIds / removedInstrumentIds / changedInstrumentIds`、`marketDataIssueIds`を含む。
`ready`は完全なcatalogと採用済み名簿の一致、`review_required`は名簿差分の確認待ちを示す。
取得元の問題は`source_unavailable / source_stale / source_incomplete / source_invalid`、
確認元の未設定は`unconfigured`。確認待ちでは新しいcatalog時刻と最後に一致した時刻を分ける。
identity fingerprintだけが異なる場合も確認待ちとし、列挙したIDが全差分を表すとは限らない。

元artifactとcatalog成功記録は30分以内、catalogはその`maxAgeSeconds`以内でなければならない。
catalog成功件数はsnapshot全件数と一致し、成功記録の完了時刻はcatalog観測時刻と同じで、
両artifactの生成時刻以前である必要がある。新しい成功記録を古いsnapshotへ流用しない。
全体statusがpartialでも、品質警告が取引所L1だけであればcatalog照合を継続する。
未知の警告、部分catalog、古い・不正な入力は拒否する。応答時にもcatalog観測から30分を超えれば
`source_stale`へ変更し、現在の差分・価格品質を未確認へ戻す。最後の名簿一致から24時間も上限とする。
`marketDataIssueIds`は同時に読んだ元Universeの価格品質がready以外のIDで、参照ランキングの価格品質とは別。
空配列は確認対象なし、nullは未確認として画面に表示する。価格欠測を理由に採用済み名簿の一致判定を失敗させない。
`/health`の名簿診断にも応答時の同じ期限切れ判定を適用する。
専用API未起動・初回世代待ち・不正な応答はWebで503、問い合わせ不正は400にする。


### 順位比較と追加指標

`metricVersion`は`trade-close-quote-turnover-analysis-v4`。応答の`previousGenerationId`と
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
DBを再参照しない。SQLiteの表は共通で、保存済みOHLCにも適用できる。

### 昨日・一昨日の同時間帯との売買代金比較

各行の`turnoverComparison`は、選択期間の`current / previousDay / twoDaysAgo`と
`previousDayRatio / twoDaysAgoRatio`を持つ。各区間は`anchor / cutoff / quoteTurnover / status`を
保持し、現在の[A,T)を24時間・48時間ずらした同じ長さで比較する。15分・1時間・24時間と、
指定JST HH:mmからTまでの可変期間に対応する。値は同じ参照契約・revisionの確定1分足の
USDT建てquote turnover合計であり、異なる銘柄、取引所、数量単位を混ぜない。

現在をQ0、昨日をQ1、一昨日をQ2としてQ0/Q1、Q0/Q2を返す。期間内の全足がそろった場合だけ
`ready`とし、足が1本でも欠ければ該当区間とその比較は`history_missing`。売買代金だけの比較に
anchorで終了する足の終値は要求しない。長さ0は`starting`、参照を利用できない場合は
`reference_unavailable`、非有限値等は`invalid_data`。実測の0は区間値として保持するが、
分母0の倍率は`no_baseline`でnullにする。Q0=0かつ分母が正の場合は倍率0を返す。

過去日の不足は現在の順位適格性や既存24時間平常比を失効させない。3日分の入力と必要な価格境界
（4,321本）を世代作成時に固定し、前世代も後着訂正で書き換えない。SQLiteは4日と1分を保持する。
比較は選択中の1期間分だけ返し、`windows`各期間へ同じ比較を重複格納しない。

### Markets workspaceの追加契約

Ranking応答`ranking-v5`は同じgenerationの15分、1時間、直近24時間、指定JST HH:mmからの変化を`windows`に保持する。`dailyReferenceJst`は従来どおり指定時刻であり、`dayRangePosition`だけがJST 00:00基準である。画面のlocal filterとsortはサーバーの全体順位を再計算しない。

`market-metrics.json`は既存4 artifactから独立した任意の読取laneで、`native-endpoints-v1`、`generationId`、`candleCutoff`、現行ID/version別の`oiChange`と`tradeChange`を保持する。数量OIは同一versionのL1 bucketの15分・1時間差。終値変化は全行共通cutoffの確定1分足の15分・1時間・24時間差であり、JST騰落率とは別の値である。180秒lagと300秒上限は設計初期値で、実データから測定した数値ではない。欠損や古い値を0へ置換しない。

`GET /api/market-metrics`はartifactだけをschema検証して返す。未生成・不正は503、正常な古いartifactは元の時刻のまま返し、Browserで鮮度を判定する。`GET/POST /api/user-workspace`はfavoriteの望む状態と名前付きviewの条件付き更新を扱う。メモは読取bytesのSHA-256 tokenを条件に保存し、`context`を添付する保存ではNoteFile v2へ移る。旧v1項目も読み続ける。

メモcontextは`ui-observation-v1`のnativeまたはreference観測。nativeは数量OI/確定終値15m、referenceはProvider・symbol・revision・cutoff・比較期間・JST設定・期限切れ状態と5個の数値を保存する。参照の保存先は現行UniverseとID/versionが一致する元契約だけ。自由形式metrics/raw/secret key、非有限数、長すぎる文字列を拒否し、最大16指標より小さい固定shapeと64KiBのPOST上限を維持する。過去の市場真実を再認証する署名ではない。

## Bitget短時間activity

任意artifact `native-activity.json`は`schemas/native-activity.schema.json`に従い、
`schemaVersion=1`、`metricVersion=bitget-activity-v1`、`generationId`、`generatedAt`、
`candleCutoff`、`rows`を持つ。対象はactiveなBitget crypto linear perpetualの現行契約版で、
quote/settleはUSDT。同一`venueInstrumentId`・versionの保存`candle_1m.volume_notional`だけを使い、
旧版、base数量の換算、reference市場、Hyperliquidの短時間値で補完しない。

`candleCutoff`は生成時刻のUTC分境界−180秒。`windows`は`15m`と`1h`で、それぞれ
`current`、現在を右端とする古い順の非重複4窓`history`、`baselineTurnover`、`baselineDays`、
採用日の終了時刻`baselineEndTimes`、`relativeRatio`、`previousChangePct`を持つ。
各sampleは`[startAt,endAt)`の全1分足のquote turnoverと、開始直前・終了直前の足の終値による
`priceChangePct`を分けて返す。足は`confirmed`または`derived_final`で、分境界・全分の存在・
非負有限のquote turnover・source/observed時刻が生成時刻より未来でないことを確認する。
価格の開始endpointだけが欠ける場合は価格変化のみ欠測とし、完全な売買代金は保持する。

普段比の分母は過去7日の同時刻・同長窓のうち、完全な3日以上の売買代金の中央値。
前区間比は直前の同長窓からの百分率変化である。数値は`{value,status}`で、`ready`だけが有限値を持ち、
`history_missing`、`invalid_data`、`no_baseline`、`low_baseline`では`value=null`とする。
分母0は`no_baseline`、15分1,000 USDT未満／1時間4,000 USDT未満は`low_baseline`で、
普段比・前区間比の両方へ適用する。元の区間値や中央値は失わず、baseline不足でも現在値・直近推移は
独立して返す。実測0は0として保持し、有効な分母に対する現在値0は倍率0・前区間比−100%となる。

`GET /api/native-activity`は`no-store`でartifactを返し、DB照会や取得を開始しない。
schemaに加え、重複identity、窓の長さ・順序・共通cutoff、現在値とhistory末尾の一致、baseline日数・
時刻、status/valueと分母条件の整合性を検証し、不正または未生成なら503を返す。
正常な古いartifactは元時刻のまま返す。Browserは生成から120秒、cutoffから300秒を超える値を
利用不可とし、生成時刻の未来許容は1秒まで、未来cutoffは拒否する。対象のBitget originalが1契約に
定まり、ID・version・source symbolが一致する場合だけ表示する。参照ランキングのAPI・順位・Chart契約は維持する。

## 保存足の補助契約

`schemas/candle-recovery-state.schema.json`は最後のRecovery runを表す任意artifact。
対象の現行ID・version・definitionHash、半開UTC窓、scan/insert/rescan件数、失敗と未処理を分ける。
`execution=running|succeeded|partial|failed`で、部分成功を全契約成功へ昇格しない。
手動scanだけではartifactを更新しない。
同じschemaを使う`candle-endpoint-recovery-state.json`は指標のexact endpointだけを回復した
別runを記録する。通常履歴の全時間格子に対する完了状態とは別であり、endpointの成功から
全履歴の完全性を主張しない。両runはversion/hashを再確認し、既存足を上書きしない。
時間上限やDB障害でscanが完了しない場合、全体の`missingBefore`・`remaining`・`newlyPresent`や
対象の未検査件数は`null`とする。挿入後に中断しても、終了を確認したDB処理の挿入件数を保持する。

Auditは`schemas/audit-request.schema.json`の手動requestをCLIだけで受け取り、
`schemas/candle-audit-report.schema.json`の不変reportと
`schemas/candle-audit-index.schema.json`の任意最新indexを発行する。入力は保存1分OHLCV、
同一Venue・symbol・version・definitionHash・base/quote/settle・trade価格・60秒区間を要求する。
`outcome=match|differences|incomplete|unverified`は計算結果、`execution`は実行成否。
前回完了runのIDは失敗した最新runと別に保持する。差異の値と欠測・不正件数は共存できる。
`schemaVersion=1`、未知schemaや破損indexを空の成功記録へ置き換えない。

Webの`GET /api/candle-recovery`と`GET /api/candle-audits`は上記の許可済みlocal / Tailscale接続限定・no-store。
未生成なら`state=not_run`、有効なら`available`、破損・読取不能なら503 `unavailable`を返す。
`GET /api/candle-audits/<runId>?offset=&limit=`は不変reportから最大200件ずつ返す。
`schemas/candle-audit-detail.schema.json`が返却形で、0始まりoffset、全集約済みmarker bucketを含む。
不正引数は400、不在runは404、破損runは503。入力path・DB・secretはHTTPへ出さない。

OpenMarketの手動mappingと取得receiptは`schemas/reference-mapping.schema.json`と
`schemas/reference-acquisition.schema.json`、Core用出力は`schemas/fixture-manifest.schema.json`。
Referenceは確認済みnative契約の別取得経路で、独立性は未確立。FixtureのDB datasetは同一
read-only repeatable-read snapshot、後から読んだartifactは別時刻と記録する。空0行、未取得、
失敗をmanifestで分ける。SHA256はファイル改変検出であり、市場の真実性署名ではない。

## Attentionの契約

正本は`apps/attention-core/src/prep_watchdeck_attention/models.py`。公開schemaは`attention-response-v1`、`attention-evaluation-v1`、`attention-shadow-allocation-v1`。Web型はresponse schemaから生成する。時刻はUTC milliseconds。`decisionAt`、Ranking cutoff/generatedAt、universe/service generatedAt、任意のmetrics generation/candleCutoffと`inputSkewSeconds`を分離する。未来、stale、異なるcontract versionを現在値で補完しない。

AssetはRankingのoriginal instrument ID + versionと現行universeの完全一致で結合する。元の対応と現行membershipを`originals`へ残し、UIは`current=false`のnative linkを出さない。未レビュー対応・version違いは採点対象外。成分の`score`/`rank`、方向、quality reason、coverageは別の値で、算出不能はscore/rank=null。percentileのminimum peersは20、同値はmidrank、confluenceは4成分すべてreadyの場合だけ平均する。異なるmap/policy間でrank changeを計算しない。

Stateは`PREP_WATCHDECK_ATTENTION_STATE_DIR`。Market/Rankingとの同一・包含・被包含、repo varとの重複、symlinkを拒否する。SQLiteはsingle writer / WAL / foreign keysで、generationの同一ID・異なる内容を拒否する。初版は自動削除を行わず、health/CLIがDB/WALサイズを報告する。

将来outcomeの`cutoff`は`ceil(decisionAt / 60000) * 60000`の評価開始境界で、入力Ranking cutoffとは別である。参照契約のその境界の確定終値をexportに要求し、以後の完全な15本・60本だけから高安の最大絶対returnと終値returnを求める。判断時刻をまたぐ足は最大変動へ含めず、保存時の古い終値で代用しない。lead timeはdecisionAtから閾値へ初めて到達した足の終了時刻までの秒。欠損・revision/map違いはunscorable、未完了horizonはpending。訂正はeditionを増やし、既存評価と出力projectionをstale化する。

Offline入力は`attention-outcome-input-v1`のJSON（`mapVersion`、Ranking `MinuteBar`の`bars`、任意の`native`）に限定する。native結果は現行のexact originalsが2 Venue以上あり、全分の観測が揃う場合だけ別familyへ保存する。

既定候補群は3 baselineと5 componentを15分・60分の各horizonで固定した16 policy。K=10/20、実用差分しきい値はreturnのpercentage pointで0.1を初期値とし、freeze後に変更できない。全比較を同時にUTC day blockで再標本化するsingle-step max-Tと6h感度分析を用いる。世代なし・将来結果待ち・block不足はnot_estimable、感度矛盾はinconclusive、実測coverage悪化はrejected_coverage。power/MDEはplanning-onlyで、優位性判定を上書きしない。
