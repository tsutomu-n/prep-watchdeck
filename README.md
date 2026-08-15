# prep-watchdeck

- 作成: `2026-06-18T04:43:28+09:00`
- 更新: `2026-08-14T23:19:15+09:00`
- 検証: `2026-08-14T23:19:15+09:00`
- 状態: `現行`

---

`prep-watchdeck`は、Bitget、Hyperliquid Core、Asterのpublic market dataを集め、
crypto linear perpetualをVenue横断で確認するlocal-firstのUniverse Explorerです。
価格、資金調達率、建玉、24時間出来高、鮮度、取得元、選択銘柄の板・約定・Chartを表示します。

売買推奨、自動売買、注文、残高、position、秘密API、RWA、HIP-3、synthetic/RFQ市場は扱いません。

## 必要なもの

- Python 3.13と`uv`
- Bun
- Docker Compose
- systemd user serviceを使う場合はLinuxのuser manager
- public market APIへ接続できるnetwork

依存を準備します。

```bash
uv sync --all-packages
cd apps/web
bun install
bun run generate:types
cd ../..
```

## Dedicated Postgres

既定のstate rootは`~/.local/share/prep-watchdeck-market`、専用Postgresのloopback portは
`127.0.0.1:55432`です。JustPassなど他projectのPostgres、port 5432、container、volume、
database、roleを再利用しません。

```bash
install -d -m 0700 "$HOME/.config/prep-watchdeck-market"
install -d -m 0700 "$HOME/.local/share/prep-watchdeck-market/postgres"
touch "$HOME/.config/prep-watchdeck-market/postgres.env"
chmod 0600 "$HOME/.config/prep-watchdeck-market/postgres.env"
```

`postgres.env`へ次を設定します。`POSTGRES_PASSWORD`はローカル専用の十分に長い値を作り、
URL側ではpercent-encodeしてください。このfileはcommitしません。

```text
POSTGRES_DB=prep_watchdeck_market
POSTGRES_USER=prep_watchdeck_market
POSTGRES_PASSWORD=<local-secret>
PREP_WATCHDECK_MARKET_DATABASE_URL=postgresql://prep_watchdeck_market:<url-encoded-secret>@127.0.0.1:55432/prep_watchdeck_market
```

productionのinstallerとCLIは、user/databaseが`prep_watchdeck_market`、host/portが
`127.0.0.1:55432`であることを検証します。隔離test/shadowで別targetを使う場合だけ、専用state/portと
`PREP_WATCHDECK_MARKET_ALLOW_NONSTANDARD_DATABASE_TARGET=true`を明示します。このoverrideを
productionの`postgres.env`へ書いてはいけません。

## systemd user service

まずrender差分を確認します。

```bash
bash scripts/ops/install-user-services.sh --dry-run
```

承認済みのローカル環境だけへunitをinstallします。`--apply`は既存unitをtimestamp付きでbackupし、
daemon-reloadとenableだけを行います。serviceのstart/restartは行いません。

```bash
bash scripts/ops/install-user-services.sh --apply
bash scripts/start-all.sh
```

既定URLは`http://127.0.0.1:5173/`です。installされる境界は次の5 unitです。

- `prep-watchdeck-market-db.service`: 専用Postgres 17 Compose
- `prep-watchdeck-market.service`: catalog、L1、candle、selected stream、artifact発行
- `prep-watchdeck-market-maintenance.service`: confirmed archiveとbounded retention
- `prep-watchdeck-market-maintenance.timer`: 毎時maintenance
- `prep-watchdeck-web.service`: localhost SvelteKit Web

Webだけをforegroundで起動する開発入口です。collectorは起動しないため、既存のmarket serviceを
重複起動しません。

```bash
bash scripts/start-local.sh
```

## Stateとread model

```text
~/.local/share/prep-watchdeck-market/
  postgres/
  archive/
  artifacts/
    universe-snapshot.json
    market-chart.json
    selected-market.json
    service-state.json
  control/selection.json
  past-notes/<venueInstrumentId>.json
  market-service.lock
  market-maintenance.lock
```

Postgresが直近データの正本、confirmed Parquetが期限後履歴の正本、4つのJSONは再生成可能な
Web read modelです。WebはPostgresへ接続しません。選択commandとPast Noteの書込みは
localhost requestだけに許可されます。

現在のartifact状態だけを確認します。別collectorやone-shot scanは起動しません。

```bash
bash scripts/update-live.sh
```

## Maintenanceとbackup

毎時timerと同じ処理を手動で実行します。

```bash
bash scripts/ops/run-market-maintenance.sh
```

毎時maintenanceは、各dataset/Venueの最古未archive日から重複を除いた最大3日と、直前の
完了UTC日を自動で処理します。`--partition-date`を指定すると、直前日ではなく指定した完了日を
優先対象へ加え、同じ自動catch-upも行います。

```bash
bash scripts/ops/run-market-maintenance.sh --partition-date YYYY-MM-DD
```

maintenanceは完了UTC日のnormalized datasetをParquetへ書き、readbackとmanifest確認後だけ8日超を
削除します。Parquet対象外と明示したephemeral rawは7日+2時間、selected raw/historyは各保持期限後に
bounded deleteします。各DELETEは最大10,000行、1回の上限はnormalized 180 batch、raw 10 batch、
selected 250 batchです。source更新のないactive manifestは再生成せず、空datasetをarchive成功として
扱いません。

Postgres backup:

```bash
bash scripts/ops/market-postgres-backup.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup-dir "$HOME/watchdeck-local-archive/market-postgres"
```

restoreはmarket serviceを停止し、対象名と`--apply`を明示する別操作です。手順は
[現行運用](docs/current/operations.md)を参照してください。

## 検証

Repo横断gateは最後に1回だけ実行します。

```bash
bash scripts/verify-local.sh
```

`TEST_DATABASE_URL`が未指定なら、gateは固定digestのPostgres 17を一時containerとして起動し、
実DB integrationをskipせず実行後にcontainerを削除します。他projectのDBは使用しません。

実market API、Postgres、Webを使うsmoke/shadowは、現役state/serviceから隔離した
DB、state root、portで実施します。test greenだけでlive cutover済みとは扱いません。

隔離shadowは最初にdry-runで全targetを確認します。state/evidence、Compose project、DB/Web port、
現役snapshot/DuckDB/unitをすべて明示し、production既定port 55432/5173とJustPass 5432は使いません。

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

dry-run差分を確認した同じ引数で`--dry-run`を`--execute`へ変更すると、15分baselineと60分shadowを
1回実行します。短い`--baseline-seconds`/`--shadow-seconds`はharness確認用で、受入証拠にはしません。
Webはbaseline前に1回buildし、shadow中はdev/HMRではなくpreviewを使います。終了時は記録した
process groupと指定Compose projectだけを停止し、証拠と専用stateはRepo外へ残します。Dockerは
ambient remote contextを使わず、rootful local `unix:///var/run/docker.sock`だけに固定します。

## 正本

- [現行ドキュメント](docs/README.md)
- [アーキテクチャ](docs/current/architecture.md)
- [データ契約](docs/current/data-contracts.md)
- [UIワークフロー](docs/current/ui-workflow.md)
- [運用](docs/current/operations.md)
- [検証](docs/current/validation.md)
- [UI設計規則](DESIGN.md)
- [Decision 0011](docs/decisions/0011-perp-universe-replacement.md)

旧scannerのstate、unit backup、稼働checkoutはcutover後のrollback確認が完了するまで削除しません。
