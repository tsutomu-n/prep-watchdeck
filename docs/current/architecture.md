# prep-watchdeck 現行アーキテクチャ

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 文書更新作業: `2026-08-12_21:38`（Asia/Tokyo）
- 状態: `現行`

---

## Process境界

scanner-coreがmarket data取得、DuckDB永続化、snapshot/chart/runtime発行を担当し、
Webはそれらのlocal fileを読み、Past NoteとDashboard view設定をlocalhost限定APIで保存する。

同じDuckDBへ複数writerを起動しない。service実行中の画面更新は
`watchdeck publish-service`を使い、別のlive scanを同じDBへ重ねない。

## データlane

### Cold snapshot

`snapshots/latest.json`は初期表示、filter、Raw Sort、Smart Rank、selected symbolの
基準となるscanner snapshotである。service publishでは重いdetail barsを含めない。

VPI-Lite+ V0はこのCold laneだけで、既存scannerの5分足集約前にclosed 1分足から計算する。
`config/vpi-lite-plus.toml`はservice起動境界で一度だけ読み、結果は補助sidecarとして
summaryと存在するrowのdisplayへ格納する。既存filter、category、attention score、
Hot ticker、DuckDB writerを変更せず、symbol単位の計算失敗でsnapshot発行を止めない。

BTC/ETH/SOLの3市場価格比較pilotは、Bitget、Hyperliquid、Bybitのpublic RESTから300秒ごとに
mark priceを取得する独立in-memory collectorである。service起動時と`publish-service`時にも1回取得し、
結果は`summary.marketComparison`だけへ格納する。取得失敗はsource単位で欠損にし、既存scanner、
DuckDB、filter、category、Hot tickerを変更しない。

### Hot ticker

`snapshots/ticker-runtime.json`は最新価格のfull stateと直近deltaを保持する。
Webは1秒pollで価格表示だけを更新し、row順、filter、ranking、draftをHot tickで
変更しない。visibility hidden中はpollを止める。

### Detail chart

`snapshots/charts/latest/<SYMBOL>.json`はschema version 2のchart payloadである。
Webは要求したtimeframeだけを返し、snapshotの`runId`とchartの`snapshotRunId`が
一致しなければfail-closedにする。

## scanner-core

- `Settings`: runtime/config/schema pathとservice tuning
- `composition.py`: provider、writer、DuckDB storeの組立
- `interfaces/cli.py`: scan、service、doctor、publish-service等のCLI
- `application/`: service runtime、publish、reconcile、backfill、chart、ticker
- `application/market_comparison.py`: 3市場価格比較pilotのin-memory更新
- `adapters/multisource_public.py`: 3社public RESTのmark price取得
- `adapters/perp_venue_public.py`: Bitget USDT Perpとdefault Hyperliquid Coreのpublic契約・市場値取得
- `application/perp_venue_comparison.py`: 5分周期の独立in-memory比較collector。検証済み契約catalog
  だけを最大30分保持し、片側障害時も市場観測値を再利用せず`unavailable`を生成する
- `vpi/`: VPI-Lite+のpure計算、state分類、公開payload serializer
- `adapters/duckdb/`: snapshot cacheとservice store
- `adapters/local_snapshot/`: atomic file publish

### Service resilience

Bitget public REST clientは15 requests/secondと10秒timeoutを維持し、429、500、502、
503、504、network timeoutだけを初回を含む最大5 attemptsで再試行する。待機は0.5秒を
基準とする上限10秒の指数backoffと0〜20%のadditive jitterで、`Retry-After`は
delta-secondsとHTTP-dateを解釈して最大60秒まで優先する。その他の4xx、invalid JSON、
Bitget business errorは即時失敗する。

process内watchdogは最新1分足timestampの絶対的な古さではなく、観測間での前進停止を
監視する。停止候補時だけBitget public RESTをprobeし、RESTも失敗中なら外部障害として
停止確認をresetする。REST正常下で停止が規定回数続いた場合だけ`ServiceStalledError`を
CLIへ伝播し、streamとstate、snapshot、ticker、backfill、reconcileの
taskをcancel/awaitして非0終了する。

watchdogはsystemdの`WatchdogSec`/`sd_notify`実装ではない。自動再起動はprocess managerの
`Restart=on-failure`へ委ねるため、Bitget障害そのものでは再起動ループを作らない。
DuckDB storeは引き続きservice process内の1 instanceだけを全taskで共有する。
Perp会場比較のperiodic loopはrefresh内部例外をsource task内に閉じて次周期を継続し、会場別status、
error、item件数、所要時間をservice logへ記録する。契約catalogと比較blockはin-memoryだけで、
DB writerや永続schemaを追加しない。snapshot生成と旧3市場refreshとの同時実行を避けるため、起動後の
最初のperiodic refreshだけ30秒遅らせ、その後は300秒間隔を維持する。periodic HTTP fetchは
同processのworker thread内に独立event loopを作り、snapshot生成や分析処理が使うmain event loopの
遅延をAPI timeoutへ波及させない。

## Web

- `src/lib/server/*-repository.ts`: snapshot、runtime、Past Note、Dashboard settingsのlocal repository
- `src/routes/api/`: local read/write API
- `src/lib/market/`: timeframe、Smart Rank、Raw Sort、Dashboard state
- `src/lib/components/dashboard/`: dense desktop/mobile監視UI
- `src/lib/components/symbol/SymbolMonitoringRail.svelte`: Symbol画面の監視材料

local write APIはlocalhostに限定する。`PREP_WATCHDECK_RUNTIME_TARGET=cloudflare`では
local command実行を許可しない。

## State root

`PREP_WATCHDECK_STATE_DIR`を共通rootとする。active state layout v2は次だけである。

- `watchdeck.duckdb`と任意のWAL
- `snapshots/`
- `past-notes/`（`current.json`と月別Archive）
- `dashboard-view-settings/`
- `usage-events/`
- `ops/`

Python `Settings`、Web `resolveStatePaths`、起動script、日次summaryが同じroot契約を使う。
監視stateの個別path環境変数は互換overrideとして残すが、退役済みrecord path overrideは
空値でもfail-closedにする。未指定時はrepoの`var/`を使用する。

`scripts/lib/resolve-state-paths.sh`はscanner-core用とWeb用の環境変数を同時にexportし、
snapshot、service state、ticker runtime、chartの指定が食い違う場合はfail-closedにする。

相対`PREP_WATCHDECK_STATE_DIR`はPython、Web、shellの全経路でRepo root基準にする。
各経路が表示する有効なstate、snapshot、DB pathは絶対pathへ正規化する。
E2E、performance、soakはstate rootの`tmp/<gate>/runtime`を各gateのstate rootとして
使い、現役DB、Past Note、Dashboard settingsへ書き込まない。

state migrationはv2 active filesだけをtargetへcopyし、source全体をRepo外Archiveへ保持する。
`STATE_LAYOUT_VERSION`がない既存Archiveはv1、厳密な`2` markerはv2として検証し、未知versionは
拒否する。日次サマリーはschema v2を`ops/daily/v2/`へ書き、既存schema v1を変更しない。

## Analysis history / OI lane

3つのscanner filter templateは`candles.min_required_bars=383`を使う。service snapshot cycleは
detail chart用に最大1177本の5分足相当（5885本の1分足）を読み、scanner分析とgap auditには末尾383本
（1915本の1分足）だけを渡す。chart sourceの長さとscanner分析の必要履歴を同じ値として扱わない。

service snapshot cycleはpublic tickerのOIを`open_interest_samples`へbulk upsertし、exact 60分lookback
bucketを一括loadする。table初期化失敗はstartup失敗、cycle中のOI store失敗はsnapshotを
degraded diagnostic付きで継続し、全OIを`UNKNOWN`にする。OIは5分bucket、24時間保持であり、
Candidateや74時間履歴の有無には依存しない。
