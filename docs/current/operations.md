# prep-watchdeck 現行運用

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-28T09:47:19+09:00`
- 検証: `2026-08-28T09:47:19+09:00`
- 状態: `現行`

---

## 安全境界

- 専用Compose project名は`prep-watchdeck-market`、host portは`127.0.0.1:55432`。
- state rootは既定`~/.local/share/prep-watchdeck-market`。
- credential fileは既定`~/.config/prep-watchdeck-market/postgres.env`、ownerは実行user、mode 0600。
- JustPassのPostgres、port 5432、container、volume、database、roleへ接続しない。
- productionのCLIはuser/database `prep_watchdeck_market`、`127.0.0.1:55432`以外を拒否する。
  非標準target overrideは隔離test/shadowだけに使い、production env fileではinstallerが拒否する。
- 同一state rootでmarket collectorを複数起動しない。unitとlocal direct起動は同じlockを使う。
- release cutover後も旧checkout、旧state、未追跡fileはrollback資産として削除しない。

## Production P0 completion

`2026-08-28T09:47:19+09:00`時点のproduction P0は`P0_COMPLETE=YES`。

- deployed source: `dc2a8d70f8247f8f49827f410e55170e37d95204`
- clean release: `/home/tn/releases/prep-watchdeck/dc2a8d7`（detached HEAD）
- state root: `/home/tn/.local/share/prep-watchdeck-market`
- database: dedicated Compose project `prep-watchdeck-market`、
  `127.0.0.1:55432/prep_watchdeck_market`、migration `1`から`4`
- units: `prep-watchdeck-market-db.service`、`prep-watchdeck-market.service`、
  `prep-watchdeck-web.service`、`prep-watchdeck-market-maintenance.service`、
  `prep-watchdeck-market-maintenance.timer`
- timer: enabledかつactive/waiting。production Archive確認後の次回予定は
  `2026-08-28T10:02:14+09:00`
- unit rollback backup: `~/.config/systemd/user/prep-watchdeck-*.bak.20260828-093628.2151863`
- legacy rollback checkout: `/home/tn/projects/prep-watchdeck`をdirty状態のまま保持

`aa57beb7fe1026c3adcfb9ccd39299443dd8ea88`以後のproduction必須修正は次の3件。

1. `8e4804887d97967f7b9b61426a60f3a905142c74`: 既存Postgres data directoryを
   unit再起動時にhost userへ`chmod`せず、container所有権を維持する。
2. `99ac0cf83e33872eacb56936ee5025cfda820548`: production backupを、明示した
   非production Compose projectとdatabaseの組だけへatomic restoreできるようにする。
3. `dc2a8d70f8247f8f49827f410e55170e37d95204`: Parquet numeric schemaを
   `Decimal(38,18)`へ固定し、row順依存のscale推論による丸めを防ぐ。

`2026-08-28T09:38:57+09:00`から`09:45:06+09:00`のproduction maintenanceはexit 0。
Fundingは1,178件すべて成功し、completed UTC day `2026-08-27`について次の9 partitionを
generation 1、schema version 1、status `confirmed`で生成した。合計2,132,729行についてmanifest row
count、unique key数、min/max timestamp、Parquet readback、file SHA-256が一致し、source row削除は0件。

| dataset | Venue | rows | SHA-256 |
| --- | --- | ---: | --- |
| `market_state_1m` | Aster | 492,376 | `b4f7ea39540467611d17bf885c5f20116a9a505b112f15a49435d89fc1d71d1a` |
| `market_state_1m` | Bitget | 421,344 | `694c1b239795205c79c3f22ad188f397d65e880134d21c8dde821820fd77798a` |
| `market_state_1m` | Hyperliquid | 160,512 | `4dd54183719c470642366c6613c518a947f79e2e59b68b0fac6e4552e04a42c1` |
| `candle_1m` | Aster | 490,661 | `6da68cb54d7686f8e5cc31e94aa71771acf9f8e0ce0336ce8faacc415302a9bd` |
| `candle_1m` | Bitget | 421,392 | `22eae361cf9f0e5e5b5b9ac67bd2758f337c3192c3e4240c105c0c02979f4864` |
| `candle_1m` | Hyperliquid | 137,252 | `1cbd74c25fff4bd4094356d69e520dad21fd26d69267554b4aa1e23fb305238a` |
| `funding_events` | Aster | 5,352 | `c46e8a56e3997473235d16153bcf16335ad04e4b5b669c306497b8a739133e74` |
| `funding_events` | Bitget | 1,200 | `8032d24e629ebb270592ae92c271bb9e5a854128b7d8cec57a4bd2ad7610b9d8` |
| `funding_events` | Hyperliquid | 2,640 | `58300c5a33815354483d98ecfd1b36bb035b069ae6030663da080d431893e85e` |

復旧可能backupは別disk `/data`にある
`/data/watchdeck-backups/market-postgres/prep-watchdeck-market-20260828T002319Z.dump`
（244,250,226 bytes、SHA-256
`676d96a83afdda427e588d08383c9d6fa78e3752582f7afff3bc387ced909163`）。このbackupは
isolated project `prep-watchdeck-market-archive-diagnose-20260828`、port `55443`へrestore済みで、
migration `1`から`4`、主要tableのrow存在、3 normalized datasetのduplicate key 0を確認した。

## 初期設定

[README](../../README.md)の専用stateと`postgres.env`を作る。実値をcommit、terminal log、
issue、文書へ貼らない。

unitのrender結果だけを確認する。

```bash
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --dry-run
```

installを承認した環境では次を実行する。既存unitは同じdirectoryへtimestamp付きでbackupされる。
この操作はunitをstart/restartしない。

```bash
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --apply
bash scripts/ops/install-user-services.sh --repo-root /absolute/clean-release --check
```

## 起動と停止

4つの常用unitを依存順で起動する。

```bash
bash scripts/start-all.sh
```

完全停止時は、最初に毎時timerを止めて新しいmaintenanceの開始を防ぐ。実行中のmaintenanceがある場合は
終了を確認し、その後Web、collector、DBの順に止める。

```bash
systemctl --user stop prep-watchdeck-market-maintenance.timer
systemctl --user show prep-watchdeck-market-maintenance.service \
  -p ActiveState -p SubState
```

`ActiveState=inactive`を確認した後だけ、次を実行する。

```bash
systemctl --user stop prep-watchdeck-web.service
systemctl --user stop prep-watchdeck-market.service
systemctl --user stop prep-watchdeck-market-db.service
```

`prep-watchdeck-market-maintenance.service`が`active`の間はDBを止めない。毎時timerだけを止め、
collectorとWebを継続する場合は最初の1 commandだけを実行する。

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

`/api/health`成功はWeb processだけの証拠。market dataは`service-state.json`のcatalog/L1 freshness、
Universe item quality、連続cycle、service logを別に確認する。

DB migration/healthを直接確認する場合は、専用database URLを現在shellへ設定する。

```bash
cd apps/market-core
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market status
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' uv run watchdeck-market health
```

## Artifactとfreshness

Web read modelは`$PREP_WATCHDECK_MARKET_STATE_DIR/artifacts/`の4 JSON。missing、invalid、staleを
前回値で上書きしない。定期更新が止まった、catalog/L1が2周期続けて閾値外、serviceがrestartを
繰り返す場合は成功扱いせず、新runtimeだけを停止する。

## Archiveとretention

timerの次回実行と結果:

```bash
systemctl --user list-timers prep-watchdeck-market-maintenance.timer
journalctl --user -u prep-watchdeck-market-maintenance.service --since '-2 days' --no-pager
```

同じunitを手動で1回起動する。

```bash
systemctl --user start prep-watchdeck-market-maintenance.service
```

foregroundで直接実行する場合は専用database URLを環境へ設定する。入口は最初に公開履歴から
精算済みFundingを最大48時間catch-upし、その後にarchive/readback/retentionを行う。Fundingの
一部Venue失敗時も成功Venueはcommitするが、maintenance完了後のexit statusは非0となる。

```bash
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' \
  bash scripts/ops/run-market-maintenance.sh
```

timerは各dataset/Venueの最古未archive日を調べ、重複を除いた古い順の最大3日と、直前の
完了UTC日を毎時処理する。停止期間が長い場合も次回以降の毎時実行で続きからcatch-upする。
`--partition-date`は直前日を任意の完了UTC日へ置き換えるが、自動catch-up最大3日は維持する。

```bash
PREP_WATCHDECK_MARKET_DATABASE_URL='<dedicated-url>' \
  bash scripts/ops/run-market-maintenance.sh --partition-date YYYY-MM-DD
```

同じmaintenanceの並行実行は
`$PREP_WATCHDECK_MARKET_STATE_DIR/market-maintenance.lock`で拒否する。

maintenanceは完了UTC日だけを対象にし、空datasetはskipする。source更新のない同じ完了UTC日の
active manifestは再生成しない。normalizedはParquet readback、row count、key、timestamp、row digest、
SHA-256、active manifestを確認した後だけ削除する。manifest confirm後のlate correctionは、retention
開始前なら新generationを作り、source row countがmanifest row count未満なら既にretention開始済みとして
停止する。

`raw_market_observations`はParquet対象外のephemeral rawとして7日+2時間後に削除する。selected rawと
selected normalized/historyもParquet対象外で、それぞれ7日+2時間、8日後に削除する。各DELETEは
最大10,000行。1回の上限はnormalized全target合計180 batch、raw 10 batch、selected 250 batch。
file欠損、checksum不一致、manifest変更、DB errorでは安全側に停止する。

保持期間:

- `raw_market_observations`と`selected_raw_observations`: 7日+2時間、Parquet対象外
- `market_state_1m`、`candle_1m`、`funding_events`: 8日、confirmed Parquet後だけ削除。
  Fundingの現在値・推定値は`market_state_1m`、精算済み履歴だけは`funding_events`に保持する。
- selected normalized/history: 8日、Parquet対象外
- Parquet: confirmed generationを履歴正本として維持
- generation file: currentと直近3 superseded

Postgres containerは異常終了時だけ最大5回再起動する。通常の起動・停止、Compose project、bind stateは
DB unitが所有し、別projectのcontainerへ対象を広げない。

## Backup

専用DBのcustom-format dumpをRepo外へ作る。

```bash
bash scripts/ops/market-postgres-backup.sh \
  --state-root "$HOME/.local/share/prep-watchdeck-market" \
  --env-file "$HOME/.config/prep-watchdeck-market/postgres.env" \
  --backup-dir "$HOME/watchdeck-local-archive/market-postgres"
```

backup scriptはCompose project label、database名、archive内容、mode 0600を確認し、同一directory内の
temporary fileからatomic renameする。

## Restore

restoreは破壊的な別操作。production targetへ戻す場合はmarket serviceとmaintenanceを停止し、
接続中clientが0であること、backupのdatabase名、専用Compose project、対象名を確認する。
`--confirm-target`と`--apply`が両方なければ変更しない。custom archiveをmode 0600の一時SQLへ
展開できたことを確認してから、`public` schemaの再作成とrestore全体を同じDB transactionで適用し、
一時SQLは成功・失敗時とも削除する。

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

production backupの復旧性確認は、別state root、別Compose project、別database、別host portの
隔離Postgresだけへ行う。`--compose-project`と`--target-database`は必ず対でproduction既定値以外へ
変更し、`--confirm-target`を隔離database名と一致させる。片側だけの変更、production project/databaseとの
混在、archive内database名が`prep_watchdeck_market`以外の場合はrestore前に拒否する。

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

隔離env fileの`POSTGRES_DB`は`--target-database`と一致させる。検査後は指定した隔離Compose projectだけを
停止し、production project、state root、databaseは変更しない。

## Cutover後のrollback

installerは既存`prep-watchdeck-web.service`を`.bak.<timestamp>`へ保存する。旧scanner unit、旧checkout、
旧DuckDB stateは自動削除しない。rollback承認後だけ次を行う。

1. 新Webと`prep-watchdeck-market.service`を停止する。
2. backup済み旧Web unitを元名へ戻し、`systemctl --user daemon-reload`する。
3. 旧`prep-watchdeck-service.service`と旧Web unitを起動する。
4. 旧snapshot更新、Web health、単一DuckDB writerを確認する。
5. 新DB/stateは調査用に残し、自動削除しない。

## 停止条件

- private/paid API、credential付きVenue API、注文endpointが必要になった。
- 値の意味、単位、finality、identityを推測しないと続行できない。
- 429、cycle overlap/backlog、DB lock継続、connection leak、Parquet照合失敗が発生した。
- JustPass資源へ接触した、または旧runtime/stateを失う操作が必要になった。
- L1 fresh率、cycle deadline、disk容量式、shadow既存影響のacceptanceを満たさない。

停止時は新shadowだけを止め、旧runtimeは変更しない。
