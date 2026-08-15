# Market専用Postgres

このCompose projectは、Prep Watchdeckのlocal market databaseだけを所有する。JustPassの
Postgres container、port、volume、database、role、env fileを再利用しない。

## Repo外stateとcredential

systemd unitのrenderまたは起動前に、Repo外へ次のdirectoryを作成する。

```bash
install -d -m 0700 "$HOME/.config/prep-watchdeck-market"
install -d -m 0700 "$HOME/.local/share/prep-watchdeck-market/postgres"
```

`$HOME/.config/prep-watchdeck-market/postgres.env`をmode `0600`で作成し、次を定義する。

```text
POSTGRES_DB=prep_watchdeck_market
POSTGRES_USER=prep_watchdeck_market
POSTGRES_PASSWORD=<generated local secret>
PREP_WATCHDECK_MARKET_DATABASE_URL=postgresql://prep_watchdeck_market:<url-encoded secret>@127.0.0.1:55432/prep_watchdeck_market
```

このfileはcommitしない。`PREP_WATCHDECK_MARKET_DATABASE_URL`は`watchdeck-market`が読み、
3つの`POSTGRES_*`変数は公式Postgres imageが読む。

## Compose契約

project名は既定`prep-watchdeck-market`、host listenerは既定`127.0.0.1:55432`に限定する。
database fileは`$PREP_WATCHDECK_MARKET_STATE_DIR/postgres`へbind mountする。Compose serviceは
異常終了時だけ最大5回再起動し、通常の起動・停止は`prep-watchdeck-market-db.service`が所有する。
隔離shadowだけは別Compose project/stateと
`PREP_WATCHDECK_MARKET_DB_PORT`を明示し、production envでは既定値を変更しない。

unit template rendererは`@REPO_ROOT@`、`@HOME_DIR@`、`@DOCKER_BIN@`、`@MARKET_STATE_ROOT@`、
`@MARKET_ENV_FILE@`を置換する。render済みunitのinstallと起動は別の操作とする。

## Backupとrestore

backupは専用Compose projectの起動後、Repo外directoryを明示して実行する。

```bash
bash scripts/ops/market-postgres-backup.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup-dir "$HOME/watchdeck-local-archive/market-postgres"
```

backupは同じdirectory内の一時fileへcustom-format `pg_dump`を書き、archive内のdatabase名を検査し、
mode `0600`へ固定してからatomic renameする。元databaseは変更しない。

restore前に`watchdeck-market`を停止する。restore入口は、Repo外にあるmode `0600`の既存backup、
専用project label、archive内database名、接続中clientが0件であることを検査する。対象名と`--apply`の
両方が一致しなければ変更しない。

```bash
bash scripts/ops/market-postgres-restore.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup "$HOME/watchdeck-local-archive/market-postgres/prep-watchdeck-market-TIMESTAMP.dump" \
  --confirm-target prep_watchdeck_market \
  --apply
```

restoreは`--clean --if-exists --single-transaction`でarchive内objectだけを置換する。検査またはrestoreが
失敗した場合は非0で停止する。JustPassのproject、port、container、volume、databaseは対象にしない。
