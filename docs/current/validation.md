# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-12T09:20:26+09:00`
- 検証: `2026-09-12T09:57:08+09:00`
- 状態: `現行`

---

## 原則

変更箇所に最も近いfocused testから実行し、Repo横断`verify-local.sh`は最終確認で1回だけ使う。
test green、HTTP health、単一snapshotだけをruntime/data quality/cutover完了の証拠にしない。

外部API、Postgres、Webを使う検証は専用database、専用の一時state root、別Web portへ隔離する。
現役DuckDB、旧scanner service、JustPass Postgres、port 5432へ接続しない。

## Market core focused gate

```bash
cd apps/market-core
uv run pytest -q <関連test>
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
```

変更種別ごとの最低確認:

- catalog: 3 adapter table、provenance、SCD2、除外、partial failure
- identity: exact base、collision、multiplier、quantity unit unknown
- L1/candle: 20秒fetch、50秒deadline、single-flight、no stale reuse、3 finality契約
- funding: settled event限定、最大48時間、Catalog version境界、冪等・conflict拒否、Venue障害分離
- selected: 1 group、primary switch、TTL、heartbeat、old task close、max20 depth、100 trades、
  stale/板不足/null book walk
- artifact: schema、median freshness/skew/parity、atomic write、invalid numeric拒否
- archive: normalized readback、manifest generation、checksum、late-correction停止、bounded retention、
  ephemeral raw age条件、selected FK順

DB integrationは専用Postgres 17を一時portで起動し、終了時に専用containerだけを停止する。

## Web focused gate

```bash
cd apps/web
bun run generate:types
bun run test
bun run check
bun run build
```

route、selection、responsiveを変えた場合は関連Playwrightを追加する。最低でもDesktop 1440pxと
Mobile 390pxで、検索/filter、行選択、primary変更、Chart、partial/unavailable、selected depth/trades、
Past Note、keyboard focus、横overflowを確認する。

Chart履歴はprovider/route unitで、銘柄の解決、native時間足、UTC境界、数値検証、排他的な
pagination、cache・timeout・Bitgetの取得間隔を確認する。E2Eは履歴APIをfixtureへ隔離し、
時間足の保持、定期更新後のズーム保持、古い応答の排除、JST表示、過去追加時の表示範囲を確認する。
接続確認では公開銘柄だけを使い、最新ページと過去ページのOHLC・日時・重複・ページ境界を照合する。
実APIの有限canary成功は、全銘柄・継続運転・本番反映の受入とは区別する。

約定騰落率は任意HH:mmのJST日次境界、基準足の完全一致、最新価格の鮮度、同じ契約versionの
価格同士の計算と、分境界をまたいだ取得中要求を新しい基準へ共有しないことをunit/APIで確認する。
Browser側は同時取得数、可視対象、非表示tab、設定・日付・
version変更後の古い応答排除、保存失敗を確認する。E2Eでは騰落率APIもfixtureへ隔離し、設定の変更・
保存・再読込、日次切替、欠測の理由表示をDesktop/Mobileで検証する。

## Docs/ops focused gate

```bash
bun test \
  scripts/maintenance/document-metadata.test.mjs \
  scripts/maintenance/document-links.test.mjs \
  scripts/maintenance/monitoring-only-boundary.test.mjs \
  scripts/maintenance/web-port.test.mjs \
  scripts/ops/install-user-services.test.mjs \
  scripts/ops/market-postgres-restore.test.mjs \
  scripts/ops/run-isolated-shadow.test.mjs

bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
bash -n scripts/start-all.sh scripts/start-local.sh scripts/update-live.sh \
  scripts/ops/install-user-services.sh scripts/ops/run-market-maintenance.sh \
  scripts/ops/market-postgres-restore.sh scripts/ops/run-isolated-shadow.sh
git diff --check
```

installer testは外部credential file、unit directory、systemctl/uv/dockerをfixtureへ隔離する。
restore testはproduction既定targetの互換性、隔離project/databaseの対指定、片側だけの変更拒否を
fake Dockerで確認する。実user unit、container、databaseをinstall/start/restart/restoreしない。

## Full local gate

```bash
bash scripts/verify-local.sh
```

`TEST_DATABASE_URL`が未指定の場合、scriptは固定digestのPostgres 17を専用一時containerと動的loopback
portで起動し、全Postgres integration testを実行後に削除する。指定する場合も隔離test DBに限定する。
DB testのskipはfull gate成功として扱わない。

順序:

1. current maintenance/ops tests
2. document metadata/link
3. workspace lock
4. market-core全pytest、Ruff、format、Pyrefly
5. ranking-core全pytest、Ruff、format、Pyrefly、schema整合
6. Web type generation、unit、Svelte check、build
7. Playwright E2E

未実行、skip、timeout、既存失敗を成功扱いしない。無関係な既存失敗は回帰と分離し、原因と
再開条件を記録する。

## 独立ランキングの検証

```bash
cd /home/tn/projects/prep-watchdeck/apps/ranking-core
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
cd /home/tn/projects/prep-watchdeck
uv run --package prep-watchdeck-ranking python scripts/ranking/generate-schema.py --check
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-reviewed
```

最後のcommandは全件照合のgateであり、現行の要確認44行が残る間は終了code 1になる。
構造検証やfixture成功と全名簿の受入を区別する。計算では確定終値、同じ期間のquote売買代金、
欠測、実0、JST日跨ぎ・任意分基準、古い要求、後着訂正、immutable generationを検証する。
Webでは期間・方向・下限・保存失敗、選択のID保持、mapから削除された選択、遅れて返る旧要求を確認する。

実Providerの有限受入は
[/home/tn/projects/prep-watchdeck/scripts/ranking/accept-live.py](/home/tn/projects/prep-watchdeck/scripts/ranking/accept-live.py)
を専用state・別port・OS書込み制限下で実行する。全対応数について15分・1時間・JST基準の
3連続世代、12条件の読取りと外部取得量の分離、実WS切断・再接続、75秒の収集停止と再開を記録する。
時間上限は900秒。原stateを隠した試験と、専用state外の書込みが拒否された証拠も別に残す。

[/home/tn/projects/prep-watchdeck/scripts/ranking/verify-live-values.py](/home/tn/projects/prep-watchdeck/scripts/ranking/verify-live-values.py)
は同じTの実API応答を独立したDecimal計算で照合する。Widgetの通常E2Eはfixtureへ隔離し、
実Widgetは契約種別・倍率・文字種・Desktop/Mobile・URL指定・検索・比較を別途確認する。
銘柄名だけでなく足・価格の描画を実画像で確認し、公開した全契約を実表示した証拠とは混同しない。

## Isolated live smoke

3 Venueのread-only smokeは各APIを必要最小回数だけ呼ぶ。確認対象:

- catalogが3回連続成功し、除外/provenance/capabilityが保存される。
- L1 fresh 120秒以内が99%以上。95%未満が2周期続けば失敗。
- 60秒cycle p95 30秒以下、max 50秒以下、overlap/backlog 0、429 0。
- confirmed/derived candleの受信分保存率100%、duplicate 0、activeの95%以上に直近5分bar。
- 3 Venueの精算済みFundingを保存し、現在値・推定値の混入、version境界以前、key conflictが0。
- Aster OIは明示null、Hyperliquid oracleをindexとして公開しない。
- Postgres commit p95 2秒以下、connection leakと次cycleまで続くlock 0。
- 選択変更後10秒以内に旧subscription解除、orphan 0。

単一成功cycleで合格にしない。private/paid endpoint、Hyperliquid requester-pays S3は使用しない。

## Shadow gate

現役runtimeを変更せず、専用DB/state/portで15分baselineと60分shadowを各1回測る。

- 旧snapshot p95がbaseline比120%以内
- 旧service `NRestarts=0`
- 現役DuckDB writer 1
- 新serviceのCPU、memory、network、DB size、raw/parquet増分を記録
- `7*raw_GB/day + 365*parquet_GB/day + 30GB <= 0.75*開始時free`

容量式、rate limit、data quality、既存影響のどれかが不合格ならcutoverへ進まない。

単一入口は`scripts/ops/run-isolated-shadow.sh`。既定はdry-runであり、state/evidence、現役read-only
snapshot/DuckDB/unit、Compose project、DB/Web portをすべて明示する。production既定55432/5173と
JustPass 5432、Repo配下state/evidence、live stateとの重複は拒否する。`--execute`時だけ15分baseline、
専用Postgres/collector/Web、60分shadow、容量sampleを順に実行する。
Webはbaseline前にproduction buildを1回完了し、shadow中はdev/HMRではなくpreviewを専用portで使う。
Dockerはambient context/remote hostを使わず、`DOCKER_CONTEXT`をunsetしてrootful local
`unix:///var/run/docker.sock`へ固定する。socketがなければ開始しない。

容量sampleはread-only DB sessionから当日UTCの`market_state_1m`、`candle_1m`、`funding_events`を
Venue別にproduction archiveと同じcolumns、schema、ZSTDで一時Parquet化する。経過時間で1日へ
外挿し25% safety marginを加える。行がないpartitionはFundingを含めて0と断定せず
`insufficient_data`とし、容量gateをHOLDにする。
一時Parquetは削除し、JSON証拠だけをRepo外へ残す。

```bash
bash scripts/ops/run-isolated-shadow.sh --dry-run \
  --state-root /absolute/repo-outside/shadow-state \
  --evidence-root /absolute/repo-outside/shadow-evidence \
  --live-state-root /absolute/live-state \
  --live-snapshot /absolute/live-state/snapshots/latest.json \
  --live-duckdb /absolute/live-state/watchdeck.duckdb \
  --live-scanner-unit prep-watchdeck-service.service \
  --compose-project prep-watchdeck-market-shadow-YYYYMMDD \
  --db-port 55442 --web-port 5183
```

短時間overrideはharnessのdry-run/動作確認専用で、AC-11/AC-12の受入値は15分/60分から変更しない。
cleanupは記録済みmarket/Web PIDと指定Compose projectだけに限定し、production unit/stateを停止・変更・
削除しない。network値はprocess帰属を証明できないため、shadow中のhost totalを上限、baseline差引後を
推定値として区別し、その限界を証拠へ残す。

harnessはHEAD、tracked binary diff、untracked file hashを含むsource digestをshadow前後で比較し、
不一致なら受入証拠としない。一致が証明するのはshadow実行中の不変だけであり、
実行後のsource変更は別に記録し、そのshadowで検証済みとは扱わない。

harnessの`summary.json`が自動判定するのは既存runtime影響、429、容量だけであり、CP-08全体のPASSでは
ない。AC-03/AC-04/AC-05/AC-07/AC-09は`database-summary.tsv`、market service log、artifactを別途
集計・照合する。429は`l1_cycle`のstructured `error_codes`にある`http_429`または
`bitget_business_429`だけを数え、ログ中の無関係な裸の数値は判定へ使わない。未照合のままsummaryだけで
cutoverへ進まない。

## 証拠

branch、HEAD、既存差分、JST時刻、command、exit code、隔離DB/state/port、実行件数、未実行項目、
runtime mutation有無、rollbackを記録する。credential、raw secret、固定PIDを文書へ残さない。

実装、focused gate、full gate、isolated smoke/shadow、最終diffのmandatory条件がすべて証拠付きで
満たされた場合だけPASS。push、merge、cutoverは別承認であり、local PASSへ含めない。
