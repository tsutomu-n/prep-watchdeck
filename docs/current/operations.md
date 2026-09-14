# prep-watchdeck 現行運用

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の範囲

この文書は**現在productionの3 Venue Perp runtime**を安全に運用する手順を記述する。
port、path、unit、artifact数、retention、public API構成等は現在のruntime contractであり、
[product boundary](product-boundary.md)が許可する将来機能を禁止するものではない。

P0 qualification時の個別commit SHA、row件数、backup hash等は当時の受入証拠であり、現在の運用手順や
将来の製品境界として扱わない。必要な履歴はGit/PR/backup evidenceから参照する。

## 安全境界

現在のPerp runtime:

- 専用Compose project名は`prep-watchdeck-market`、host portは`127.0.0.1:55432`。
- state rootは既定`~/.local/share/prep-watchdeck-market`。
- credential fileは既定`~/.config/prep-watchdeck-market/postgres.env`、ownerは実行user、mode 0600。
- JustPass等の他projectのPostgres、container、volume、database、roleへ接続しない。
- production CLIは現在の専用database targetを検証する。
- 非標準target overrideは隔離test/shadowだけに使う。
- 同一state rootでmarket collectorを複数起動しない。
- rollback確認前に旧checkout/stateを不可逆削除しない。

これらの具体的project名、port、pathは現行runtime値であり、将来の新app/sourceへ永久固定しない。

## P0 completionの扱い

Watchdeck v1 P0のRepository実装とproduction qualificationは完了済み。P0 Freezeは当時のscopeを完成させるための
履歴であり、P0後のranking、Stocks、ML、paid read-only API等を禁止するものではない。

現行productionの変更はP0を再開するのではなく、新しいtaskとして設計・検証する。

## 初期設定

[README](../../README.md)の専用stateと`postgres.env`を作る。実credentialをcommit、terminal log、issue、文書へ
貼らない。

unit renderだけ確認する。

```bash
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --dry-run
```

承認済み環境へinstallする。

```bash
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --apply
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --check
```

installerは既存unitをbackupする。installとruntime start/restartを同一操作とみなさない。

## 起動と停止

現在のunitを依存順で起動する。

```bash
bash scripts/start-all.sh
```

完全停止では、まずmaintenance timerを止め、実行中maintenanceの終了を確認する。

```bash
systemctl --user stop prep-watchdeck-market-maintenance.timer
systemctl --user show prep-watchdeck-market-maintenance.service \
  -p ActiveState -p SubState
```

`ActiveState=inactive`確認後:

```bash
systemctl --user stop prep-watchdeck-web.service
systemctl --user stop prep-watchdeck-market.service
systemctl --user stop prep-watchdeck-market-db.service
```

maintenance serviceが`active`の間はDBを止めない。

## 状態確認

```bash
systemctl --user show \
  prep-watchdeck-market-db.service \
  prep-watchdeck-market.service \
  prep-watchdeck-web.service \
  prep-watchdeck-market-maintenance.timer \
  -p Id -p ActiveState -p SubState -p MainPID -p NRestarts

journalctl --user -u prep-watchdeck-market.service --since '-15 min' --no-pager
curl --fail http://127.0.0.1:5173/api/health
bash scripts/update-live.sh
```

`/api/health`成功はWeb processだけの証拠。market dataはartifact freshness、Universe item quality、連続cycle、
service logを別に確認する。

DB migration/health:

```bash
cd apps/market-core
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market status
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market health
```

## Artifactとfreshness

現在のWeb read modelは`$PREP_WATCHDECK_MARKET_STATE_DIR/artifacts/`に4 JSONを持つ。
missing、invalid、staleを前回値で上書きしない。

4 artifactは現在の実装数であり、ranking/model/Stocks等の新artifactを追加できる。

定期更新停止、freshness閾値超過、restart loop等は現在のruntime障害として扱う。

## Archiveとretention

現在のtimer確認:

```bash
systemctl --user list-timers prep-watchdeck-market-maintenance.timer
journalctl --user -u prep-watchdeck-market-maintenance.service --since '-2 days' --no-pager
```

手動で1回起動:

```bash
systemctl --user start prep-watchdeck-market-maintenance.service
```

foreground実行:

```bash
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' \
  bash scripts/ops/run-market-maintenance.sh
```

指定partition:

```bash
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' \
  bash scripts/ops/run-market-maintenance.sh --partition-date YYYY-MM-DD
```

同じmaintenanceの並行実行はstate rootのlockで拒否する。

現在のmaintenanceは、normalized Parquetのreadback、row count、key、timestamp、row digest、SHA-256、active manifestを
確認した後だけ対応sourceを削除する。空datasetをarchive成功として捏造しない。

現在の保持期間:

- raw market / selected raw: 7日+2時間
- current Postgres上のnormalized / selected history: 8日を基準にbounded retention
- confirmed Parquet: retention後履歴正本
- generation file: currentと直近supersededを限定保持

**これらの日数・batch上限は現行capacity policyであり永久制約ではない。** Ranking、長期feature、Stocks等の
要件に応じて、新dataset/laneまたはretention policyを検証付きで追加・変更できる。

file欠損、checksum不一致、manifest conflict、DB errorでは安全側に停止する。

## Backup

専用DBのcustom-format dumpをRepo外へ作る。

```bash
bash scripts/ops/market-postgres-backup.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup-dir "$HOME/watchdeck-local-archive/market-postgres"
```

backup scriptはtarget、archive内容、file modeを確認し、temporary fileからatomic renameする。

## Restore

restoreは破壊的な別操作。production targetへ戻す場合はmarket service/maintenanceを停止し、接続中client、backup、
Compose project、database名を確認する。`--confirm-target`と`--apply`なしでは変更しない。

```bash
systemctl --user stop prep-watchdeck-market.service
systemctl --user stop prep-watchdeck-market-maintenance.timer

bash scripts/ops/market-postgres-restore.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup "$HOME/watchdeck-local-archive/market-postgres/prep-watchdeck-market-TIMESTAMP.dump" \
  --confirm-target prep_watchdeck_market \
  --apply
```

復旧性確認は別state root、別Compose project、別database、別host portの隔離Postgresで行う。

```bash
PREP_WATCHDECK_MARKET_DB_PORT=55442 docker compose \
  --project-name prep-watchdeck-market-restore-YYYYMMDD \
  --env-file /absolute/isolated/postgres.env \
  --file deploy/market-postgres/compose.yaml up --detach --wait postgres

bash scripts/ops/market-postgres-restore.sh \
  --state-root /absolute/isolated/state \
  --env-file /absolute/isolated/postgres.env \
  --backup /absolute/backup/prep-watchdeck-market-TIMESTAMP.dump \
  --compose-project prep-watchdeck-market-restore-YYYYMMDD \
  --target-database prep_watchdeck_market_restore_yyyymmdd \
  --confirm-target prep_watchdeck_market_restore_yyyymmdd \
  --apply
```

検査後は指定した隔離Compose projectだけを停止する。

## 現行Perp runtimeのrollback

旧scanner unit、旧checkout、旧DuckDB stateがrollback資産として残っている環境では、rollback承認後だけ利用する。

1. 新Webとmarket serviceを停止する。
2. backup済み旧Web unitを復元しdaemon-reloadする。
3. 旧serviceを起動する。
4. 旧snapshot/Web health/writerを確認する。
5. 新DB/stateは調査用に残し、自動削除しない。

これはP0移行のrollback pathであり、新しいStocks/ranking/model surfaceのrollback方式を永久固定しない。

## 現行runtimeの停止・HOLD条件

次では、変更中の新task/shadow/cutoverをHOLDして原因を解消する。

- sourceの意味、unit、finality、identityを確認できず推測が必要になった。
- 429、cycle overlap/backlog、DB lock、connection leak、archive/readback照合失敗等が受入条件を外れた。
- 他project資源へ接触した、またはrollback資産を意図せず失う操作が必要になった。
- data quality、capacity、既存runtime影響等のtask固有acceptanceを満たさない。
- 新credential/sourceを導入するのに、auth scope、secret handling、terms、rate limit、rollbackが未設計である。

**paid APIやcredential付きread-only APIであること自体は製品全体の停止条件ではない。** 正規のread-only sourceは
Decision 0012の範囲内であり、scopeと安全性を確認して導入できる。

注文/write権限を持つcredentialや自動executionを導入する場合は、Decision 0005に従い別Decisionを要求する。
