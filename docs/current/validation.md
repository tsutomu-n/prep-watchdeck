# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T19:56:52+09:00`
- 検証: `2026-09-16T19:56:52+09:00`
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
5. ranking-core全pytest、Ruff、format、Pyrefly、schema整合、map根拠整合とランキング採用資格の全件照合gate
6. Web type generation、unit、Svelte check、build
7. Playwright E2E

未実行、skip、timeout、既存失敗を成功扱いしない。無関係な既存失敗は回帰と分離し、原因と
再開条件を記録する。

## 独立ランキングの検証

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700
uv run --package prep-watchdeck-ranking python scripts/ranking/generate-schema.py --check
uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-ranking-qualified
```

最後のcommandは原資産同一性・固定参照契約の全件照合gateであり、行の要確認が残る間は終了code 1になる。
/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/verify-local.sh にも組み込み、未照合のままfull gateを成功させない。
元数量倍率・Widgetの未確認は件数と機能への影響を独立して報告する。両方も確認済みであることを
要求する旧`--require-reviewed`は維持し、未確認が残る間は終了1とする。
map根拠整合commandの成功、`rankingQualified`、`qualificationComplete`、実データ受入を区別する。
全件照合gateで停止した後にWebを個別検証しても、full gateの終了結果は失敗のまま記録する。
要確認の件数・理由は /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core/data/README.md を参照する。

計算では確定終値、同じ期間のquote売買代金、欠測、実0、JST日跨ぎ・任意分基準、古い要求、後着訂正、
immutable generationを検証する。Providerの不正な応答構造は検証エラーとして扱い、収集の再接続と
補完workerの継続を確認する。RESTはcatalog取得も含めて各Provider同時2接続以内とする。
Webでは期間・方向・下限・保存失敗、選択のID保持、遅れて返る旧要求を確認する。
mapから削除された選択については、その後の期間・並び順・下限変更で応答が遅延・失敗しても
旧Widgetが復活しないこと、新しく選んだ有効銘柄のWidgetを表示できることを確認する。

実Providerの有限受入は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/accept-live.py](../../scripts/ranking/accept-live.py)
を専用state・別port・OS書込み制限下で実行する。全対応数について15分・1時間・JST基準の
3連続世代、12条件の読取りと外部取得量の分離、実WS切断・再接続、75秒の収集停止と再開を記録する。
時間上限は900秒。原stateを隠した試験と、専用state外の書込みが拒否された証拠も別に残す。
map versionと対応範囲を受入証拠へ結び付け、異なるmapでの全件成功を新mapの全件受入へ流用しない。
実Widgetの追加銘柄が表示できても、追加後mapの全Provider取得・連続更新の受入とは区別する。

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/scripts/ranking/verify-live-values.py](../../scripts/ranking/verify-live-values.py)
は同じTの実API応答を独立したDecimal計算で照合する。`--port`の代わりに`--snapshot`で
有限受入が保存した全期間の同一世代を指定でき、`--asset`の繰り返しで追加の必須対象を選べる。
元数量未確認の新規採用行も指定し、同じ参照のREST足と4指標を照合する。
Widgetの通常E2Eはfixtureへ隔離し、
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

## 日常利用の追加指標と再開受入

順位変化は、直前の発行済み世代・同条件の再計算・同順位・新規・現在順位外・欠落・再起動・
map/指標変更・JST基準切替・後着訂正を検証する。直近24時間内の同期間中央値との比較は
最新窓除外・95窓/23窓・0・基準0・1本の欠測を、当日高安位置はhigh/lowと終値の違い・
JST 00:00・値幅0・範囲外入力を手計算fixtureで照合する。新指標の欠測で既存順位を変えない。

Gitの除外設定によりPyreflyのproject検査が未追跡testsを省略する作業先では、対象fileを明示して
検査した結果も残す。現在のランキングmoduleの補完commandは次のとおり。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-continuation-20260912-115700/apps/ranking-core
uv run pyrefly check --config pyproject.toml --use-ignore-files=false src/prep_watchdeck_ranking/*.py tests/*.py
```

有限helperの`--prepare-only`は空の専用stateの履歴準備と通常3連続世代だけを確認する。
全対応契約について既存3期間に加え、15分/1時間の平常比とJST当日高安位置の入力がそろうことを
検査する。各指標のstatus内訳、順位変化のstatus、除外理由、共通T、処理時間、RSS、Provider取得数を
世代ごとに残す。各実行は最大900秒を維持し、成功した準備証拠はpreparation.jsonへ出力する。

復旧は`--prepare-only`なしの別実行とし、通常3連続世代、12条件読取り、実WS切断・再接続、
75秒停止、保存済みstateから再開後3連続世代をacceptance.jsonへ記録する。初回と再開時に
比較元の世代がないこと、その後の世代が同条件で比較可能なことも確認する。空state受入を
保存済みstateからの試験で置き換えない。source hash/map/実行時刻と隔離証拠を各実行へ結び付ける。

実API照合helperは、代表Bybit/Binance契約と対応する数量倍率契約について同じTの24時間確定足を
独立したDecimal計算で比較する。既存の騰落率・売買代金と新しい中央値比・high/low位置を照合し、
元API応答・入力窓・中央値・高値・安値・終値・差を保存する。これも全契約の実値照合とは区別する。

Desktop/Mobileでは実レスポンスと表示値、設定変更、選択保持、初回・更新停止の理由、
Widgetの契約・足・価格描画を確認する。fixtureのWidgetと実TradingView受入の記録は分離する。
