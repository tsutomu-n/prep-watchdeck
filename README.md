# prep-watchdeck

- 作成: `2026-06-18T04:43:28+09:00`
- 更新: `2026-09-14T20:04:38+09:00`
- 検証: `2026-09-14T20:04:38+09:00`
- 状態: `現行`

---

`prep-watchdeck`は、裁量トレーダーが市場から注目対象を発見し、分析し、比較し、最終判断を行うための
local-first market intelligence workspaceです。

現在のproduction runtimeはBitget、Hyperliquid Core、Asterのpublic crypto linear perpetualを扱う
Perp Universe Explorerです。価格、Funding、OI、24時間出来高、鮮度、取得元、安全にgroup化できた選択銘柄の
板・約定・Chartを表示します。

**現在の3 Venue Perp実装を、将来のWatchdeck全体の上限として扱いません。** Ranking、Stocks/ETF/RWA、
追加Venue、read-only paid API、prediction/ML、backtest、Decision Memo / Trade Journal等は、必要な契約と検証を
伴って追加できます。自動注文、資金移動、無人executionは現在の既定責務に含めません。

製品境界は[現行product boundary](docs/current/product-boundary.md)と
[Decision 0012](docs/decisions/0012-product-evolution-boundary.md)を正本とします。

初めて現在のPerp runtimeを操作する場合は[ユーザーマニュアル](docs/current/user-manual.md)から読んでください。

## 必要なもの

現在のPerp runtime:

- Python 3.13と`uv`
- Bun
- Docker Compose
- systemd user serviceを使う場合はLinux user manager
- 現在のpublic market APIへ接続できるnetwork

依存を準備します。

```bash
uv sync --all-packages
cd apps/web
bun install
bun run generate:types
cd ../..
```

## Dedicated Postgres

現在のPerp runtimeの既定state rootは`~/.local/share/prep-watchdeck-market`、専用Postgresのloopback portは
`127.0.0.1:55432`です。他projectのPostgres、container、volume、database、roleを再利用しません。

```bash
install -d -m 0700 "$HOME/.config/prep-watchdeck-market"
install -d -m 0700 "$HOME/.local/share/prep-watchdeck-market/postgres"
touch "$HOME/.config/prep-watchdeck-market/postgres.env"
chmod 0600 "$HOME/.config/prep-watchdeck-market/postgres.env"
```

`postgres.env`へ現在のPerp DB設定を置きます。実credentialはcommitしません。

```text
POSTGRES_DB=prep_watchdeck_market
POSTGRES_USER=prep_watchdeck_market
POSTGRES_PASSWORD=<local-secret>
PREP_WATCHDECK_MARKET_DATABASE_URL=postgresql://prep_watchdeck_market:<url-encoded-secret>@127.0.0.1:55432/prep_watchdeck_market
```

現在のproduction installer/CLIはこの専用targetを検証します。別targetを使うtestはproductionから隔離します。

## systemd user service

render差分を確認します。

```bash
bash scripts/ops/install-user-services.sh --dry-run
```

承認済みlocal environmentへ適用します。

```bash
bash scripts/ops/install-user-services.sh --apply
bash scripts/start-all.sh
```

現在の既定URLは`http://127.0.0.1:5173/`です。現在installされる主なunit:

- `prep-watchdeck-market-db.service`: 専用Postgres 17 Compose
- `prep-watchdeck-market.service`: catalog、L1、candle、selected stream、artifact発行
- `prep-watchdeck-market-maintenance.service`: archiveとbounded retention
- `prep-watchdeck-market-maintenance.timer`: maintenance timer
- `prep-watchdeck-web.service`: SvelteKit Web

これらのport、unit構成、localhost配置は現行runtimeの実装値であり、将来の永久制約ではありません。

Webだけをforegroundで起動する開発入口:

```bash
bash scripts/start-local.sh
```

## Stateとread model

現在のPerp runtime:

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

Postgresがcurrent/recent truth、confirmed Parquetが期限後履歴正本、現在の4 JSONはWeb用read modelです。
**4 artifactだけに将来固定しません。** Ranking、Stocks、model output、journal等は新artifact/schema/APIを追加できます。

現在のartifact状態を確認します。

```bash
bash scripts/update-live.sh
```

## Maintenanceとbackup

現在のmaintenanceを手動で実行します。

```bash
bash scripts/ops/run-market-maintenance.sh
```

現在はnormalized datasetをParquet readback/manifest確認後にbounded retentionします。raw、normalized、selectedの
具体的保持期間やbatch上限は現在のcapacity policyであり、検証を伴って変更できます。

指定日を加える場合:

```bash
bash scripts/ops/run-market-maintenance.sh --partition-date YYYY-MM-DD
```

Postgres backup:

```bash
bash scripts/ops/market-postgres-backup.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup-dir "$HOME/watchdeck-local-archive/market-postgres"
```

restoreは破壊的操作なので[現行運用](docs/current/operations.md)に従います。

## 検証

PRでは変更範囲に近いgateだけを実行します。docs-only変更でPostgresやChromiumを起動せず、Market Core変更では
isolated Postgresを含むPython gate、Web変更ではunit/check/buildとdesktop E2E、ops変更ではruntime/install/restore
safety testを実行します。

Repo横断のfull local gate:

```bash
bash scripts/verify-local.sh
```

`main`へのpushとfull local gateでは全surfaceを確認し、Playwrightはdesktopとmobileを実行します。
詳細は[現行検証](docs/current/validation.md)を参照してください。

P0移行時に使用した旧DuckDB baseline、固定15分/60分shadow harnessと専用capacity samplerは退役済みです。
新しいsource、ranking、asset class、model等では変更riskに合うvalidationを定義します。

## 正本

### 製品境界

- [現行製品境界](docs/current/product-boundary.md)
- [Decision 0012](docs/decisions/0012-product-evolution-boundary.md)

### 現在のPerp runtime

- [ユーザーマニュアル](docs/current/user-manual.md)
- [現行ドキュメントindex](docs/README.md)
- [アーキテクチャ](docs/current/architecture.md)
- [データ契約](docs/current/data-contracts.md)
- [UIワークフロー](docs/current/ui-workflow.md)
- [運用](docs/current/operations.md)
- [検証](docs/current/validation.md)
- [Design Guide](DESIGN.md)
- [Decision 0011](docs/decisions/0011-perp-universe-replacement.md)

旧scanner/state/unit等はrollbackまたは履歴資産として残る場合がありますが、存在だけを現行機能や将来禁止の根拠に
しません。
