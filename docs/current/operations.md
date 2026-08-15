# prep-watchdeck 現行運用

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-15T11:04:37+09:00`
- 検証: `2026-08-15T11:04:37+09:00`
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
- live cutover、旧unit停止、旧state削除は別の明示承認まで行わない。

## 初期設定

[README](../../README.md)の専用stateと`postgres.env`を作る。実値をcommit、terminal log、
issue、文書へ貼らない。

unitのrender結果だけを確認する。

```bash
bash scripts/ops/install-user-services.sh --dry-run
```

installを承認した環境では次を実行する。既存unitは同じdirectoryへtimestamp付きでbackupされる。
この操作はunitをstart/restartしない。

```bash
bash scripts/ops/install-user-services.sh --apply
bash scripts/ops/install-user-services.sh --check
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

foregroundで直接実行する場合は専用database URLを環境へ設定する。

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
- `market_state_1m`、`candle_1m`、存在する`funding_events`: 8日、confirmed Parquet後だけ削除。
  現行collectorは`funding_events`を生成せず、funding値は`market_state_1m`に保持する。
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

restoreは破壊的な別操作。market serviceとmaintenanceを停止し、接続中clientが0であること、
backupのdatabase名、専用Compose project、対象名を確認する。`--confirm-target`と`--apply`が
両方なければ変更しない。

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
