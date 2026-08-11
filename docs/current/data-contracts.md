# prep-watchdeck 現行データ契約

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-11T10:54:58+09:00`
- 検証: `2026-08-11T10:54:58+09:00`
- 文書更新作業: `2026-08-11_10:54`（Asia/Tokyo）
- 状態: `現行`

---

## Snapshot

正本schemaは`schemas/scanner-snapshot.schema.json`。scanner-coreのPydantic DTOから
exportし、Web型は`bun run generate:types`で生成する。

top-level必須field:

- `schemaVersion`
- `engineVersion`
- `featureVersion`
- `rulesetVersion`
- `configHash`
- `runId`
- `generatedAt`
- `dataAsOf`
- `snapshotStatus`
- `source`
- `summary`
- `rankings`
- `rows`

fieldの完全な型、nested必須field、制約はschemaを正本にする。fieldの追加・変更はschema、
generated type、producer、consumer、testsを同時に更新する。

### VPI-Lite+ V0 sidecar

serviceが生成するCold snapshotだけ、`summary.vpiLitePlus`を追加できる。summaryが正本で、
`schemaVersion: 1`、`mode: "lite_plus_v0"`、`generatedAt`、`benchmarks`、`targets`を持つ。
各symbol itemは次だけを公開する。

- `symbol`
- `state`
- 0..100の`score`
- `reasonCodes`、`riskTagCodes`
- `fundingState`、`openInterestState`
- `dataQuality`
- nullableな`dataAsOf`

内部pressure、diagnostics、1分足配列は公開しない。実在するscanner rowとsymbolが一致する場合だけ、
同じitemを`row.display.vpiLitePlus`へ複製する。benchmarkはscanner rowがなくてもsummaryへ残る。
configが未指定またはdisabled、通常のlive/fixture scanではblock自体を追加しない。

Webはこのoptional sidecarを局所parserでfail-closedに検証する。top-level契約が不正ならVPI全体を
表示せず、不正なitemだけならそのitemを除外する。既存snapshot schemaのrequired fieldにはせず、
generated typeへ手書きfieldを追加しない。Hot ticker payloadはVPIを持たず、Cold snapshotを次に
発行するまでVPI値は変化しない。

VPI stateは`CALM | EARLY_ACTIVITY | ACTIVE_MOVE | THIN_VOLATILITY |
SINGLE_BAR_SUSPECT | DATA_INSUFFICIENT | DATA_STALE | UNKNOWN`、data qualityは
`OK | INSUFFICIENT | STALE | ERROR`である。これはscanner rowの`dataQuality`とは別契約である。

Dashboard discovery laneでの分類とempty state契約:

- `EARLY_ACTIVITY | ACTIVE_MOVE`は`活動増加`、`THIN_VOLATILITY | SINGLE_BAR_SUSPECT`は
  `要注意`へ分類する。
- `VPI対象 N / Watchlist M銘柄`の`N`はvalidなTarget item数、`M`は現在のWatchlist表示条件に
  含まれるrow数である。discovery buttonは両方に含まれるTargetだけを選択対象にする。
- valid summaryにTargetがなければ`VPI判定対象なし`、Targetはあるが現在の表示条件に該当しなければ
  `現在の表示条件に該当するVPI対象なし`、対象はあるが活動増加・要注意がなければ`活動急増なし`、
  payloadが欠損またはinvalidなら`VPIデータ不足`とする。
- Benchmarkはdiscovery laneのcoverageと選択対象へ含めない。

## Data quality

rowの`dataQuality`は`OK | STALE | MISSING | PARTIAL`、snapshotの`snapshotStatus`は
`OK | STALE | PARTIAL | ERROR`である。stale、gap、coverage、unsupported symbolをUIで隠さず、
価格方向やrankingとは別の意味として扱う。

row qualityの表示labelは`PARTIAL`=`一部データ不足`、`STALE`=`更新遅延`、`MISSING`=`判定不能`で、
未知値もfail-closedで`判定不能`とする。`OK`は通常rowで常時表示しない。snapshot全体の状態は
source bannerで別に示す。

## Service state

`snapshots/service-state.json`はschema version 1で、`generatedAtMs`、nullableな
`dataAsOfMs`、`productType`、stream件数、`diagnostics`、nullableな`backfill`、
`reconcile`、`deepBackfill`を持つ。scanner-coreのPydantic producerは必須field、数値制約、
未知fieldを厳格に検証する。

Web consumerはJSON構文エラーを`unreadable`として扱う一方、構文上有効な部分欠損objectは
表示用の既定値へ落とす。したがって、Web read時にproducerと同じ完全schemaを再検証する契約では
ない。file missingは`/api/service-state`で404、read failureは503、存在時はraw stateと
要約viewを返す。

## Chart

detail chartはschema version 2で、次を持つ。

- `snapshotRunId`
- `symbol`
- `generatedAt`
- `dataAsOf`
- timeframe別bars

producerは同一timestampを最後のbarへ正規化して昇順にし、timeframeごと128本以下にする。
Web consumerはschema version、symbol、timestamp昇順かつ重複なし、正数OHLC、非負
`quoteVolume`、128本上限を検証する。snapshotと`runId`が一致しないchartは表示しない。
chart APIは`runId`必須、`tf`省略時は`15m`、file missing時は指定timeframeの空配列を返し、
run mismatchは409、invalid artifactは503とする。

## Hot ticker

ticker runtimeはschema version 1で、正整数かつ単調増加する`sequence`、非負整数`asOf`、
full updates、直近delta updatesを持つ。unsafe symbol、同一array内の重複symbol、
非正数price、非正整数timestampを拒否し、deltaの各rowがfullの同一rowと一致することも検証する。

`/api/runtime/tickers?after=<sequence>`は、現在値と同じなら204、現在値の直前なら
`full=false`のdelta、それ以外なら`full=true`のrecovery batchを返す。file missingも204である。
`after`は数字だけのsafe integerでなければ400とする。

## Monitoring state

active state layout v2でWebが所有する保存契約は次の2つである。

- `past-notes/current.json`: `{ notes: PastNote[] }`
- `dashboard-view-settings/current.json`: schema version 1のDashboard view設定

`PastNote`は`symbol`、`reason`、`observedAt`、`expiresAt`、`note`を持つ銘柄annotationである。
同一`symbol`と`reason`の保存はcurrent内を置換する。`observedAt`から60日経過、または
`expiresAt`到達のどちらか早い時点でcurrentから外し、観測月ごとの
`past-notes/archive/YYYY-MM/past-notes-YYYY-MM.json`へ重複排除して保存する。

Dashboard view設定はDashboardの表示条件を保持する。内部categoryの`NO_TRADE`はsnapshotと
filter contractとして維持し、UIでは`監視除外候補`と表示する。

## 日次サマリー

`scripts/ops/watchdeck-daily-summary.mjs`はschema version 2を
`ops/daily/v2/YYYY-MM-DD.json`へ、任意のMarkdownを同directoryへ書く。入力はusage events、
snapshot、Past Note、Dashboard settingsだけである。既存の`ops/daily/YYYY-MM-DD.*`
schema v1 artifactは履歴として保持し、上書きしない。

## Local API

### Market / runtime read

| Method | Route | 役割 |
| --- | --- | --- |
| GET | `/api/health` | Web processのhealth |
| GET | `/api/latest` | 最新snapshot |
| GET | `/api/dashboard/snapshot` | Dashboard用Cold snapshot。`afterRunId`対応 |
| GET | `/api/runtime/tickers` | Hot ticker full/delta batch。`after`対応 |
| GET | `/api/service-state` | service runtime state |
| GET | `/api/symbols` | symbol一覧 |
| GET | `/api/symbols/[symbol]` | symbol detail |
| GET | `/api/symbols/[symbol]/chart` | timeframe別chart。`runId`必須、`tf`対応 |
| GET | `/api/rankings` | ranking |
| GET | `/api/summary` | snapshot summary |

### Monitoring state

| Method | Route | 役割 |
| --- | --- | --- |
| GET / POST | `/api/past-notes` | Past Noteの取得・作成 |
| GET / PATCH | `/api/dashboard-view-settings` | Dashboard view設定の取得・変更 |

mutation methodはlocalhostからだけ許可する。read methodはlocal file repositoryを読む。
record format、file lock、atomic writeのvalidationは各repositoryとroute testを正本にする。

`/api/dashboard/snapshot?afterRunId=<current-run-id>`は変更がなければ204を返す。

### 非目標となった旧API

`/api/trade-memos`、`/api/attack-tickets`、`/api/weekly-review`にはproduction routeを置かない。
GET、POST、PATCH、PUT、DELETEはいずれも404であり、CSV exportも提供しない。

### Local command

| Method | Route | 役割 |
| --- | --- | --- |
| POST | `/api/refresh-live` | `publish-service`を使うsnapshot再発行、または既存snapshot再読込 |

`refresh-live`はlocalhostに加えて、local runtimeかつ
`PREP_WATCHDECK_ENABLE_LOCAL_COMMANDS=true`の明示opt-inが必要である。
`PREP_WATCHDECK_RUNTIME_TARGET=cloudflare`では有効化しない。
同時requestは1つへ集約する。DuckDB lockだけは失敗にせず既存latest snapshotを返し、
`fallback.reason=DUCKDB_LOCK`で再発行されなかったことを明示する。それ以外の実行失敗は503とする。

## Candidate 74h / OI 60分

`featureVersion`は`4`、`rulesetVersion`は`3`、`schemaVersion`は`1`である。feature 4は
1h/4h量倍率と表示専用activity phaseを追加し、74h Candidate / OI契約自体は変更しない。
74h価格・売買代金
componentと`userRule74hMatched`は`true | false | null`で、componentのどちらかが`null`なら
複合値も`null`になる。

`summary.candidateRule74h`は`operator=AND`、価格閾値、turnover閾値、
`turnoverMode=current_24h_vs_74h_ago_24h`、`eligible/notMatched/unknown`件数を持つ。
Candidateの`rankings.timeframes`は複合値`true`かつ非`NO_TRADE`だけを含み、
`rankings.noTrade`は全rows由来の診断を維持する。

`summary.volumeRatio15m`は量倍率計算を変えず、Webへ基準の意味を渡す追加metadataである。
`windowMinutes=15`、`sampleStepMinutes=5`、`baselineSampleCount`、
`approxBaselineSpanMinutes=baselineSampleCount * sampleStepMinutes`、`statistic=median`、
`floorUsdt`を持つ。sample countとfloorはactive filter config由来で、LiveとFixtureが同じ意味を出す。
旧config名`baseline_window_bars`と`schemaVersion=1`は変更しない。

rowの`volumeRatioByTf`は15mの既存値に加えて1hと4hを持てる。各値は現在windowのUSDT売買代金を、
同じwindow幅のrolling baseline直近`baseline_window_bars` sampleのmedianで割る。sample stepは5分、
windowは15m=3本、1h=12本、4h=48本である。必要履歴、有限値、正のbaseline、floorを満たさない
windowだけ`null`にする。5m/24h/74hは量倍率を生成しない。

rowのoptional `activityPhase`は`BURST | EXPANDING | SUSTAINED | COOLING | NORMAL | UNKNOWN`である。
判定順はUNKNOWN、COOLING、SUSTAINED、EXPANDING、BURST、NORMALを固定し、required ratioが欠ける時は
UNKNOWNとする。これはdisplay-only契約であり、attention score、category、Candidate ranking、
Raw Sort、補正順位、VPI-Lite+計算へ入力しない。

表示labelは`BURST`=`急増`、`EXPANDING`=`拡大`、`SUSTAINED`=`持続`、`COOLING`=`失速`、
`UNKNOWN`=`判定不能`とする。`NORMAL`は通常状態のnoiseを避けるためrowでは省略する。

`open_interest_samples`は`(symbol,bucket_ts_ms)`主キー、`holding_amount`、`source_ts_ms`、
`updated_at_ms`を持つadditive DuckDB tableである。bucketはsource `ts`の5分floor、同bucketは
より新しいsource時刻だけ更新し、24時間より古いrowだけを削除する。OI cycle障害は
`summary.oiDiagnostics.status=degraded`と`code=OI_HISTORY_UNAVAILABLE`で可視化する。
公開する状態名とUIは60分比較に固定されているため、`change_lookback_minutes`の現在の許容値も
`60`だけとする。
