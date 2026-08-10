# prep-watchdeck 現行運用

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-10T14:13:39+09:00`
- 検証: `2026-08-10T14:13:39+09:00`
- 文書更新作業: `2026-08-10_14:13`（Asia/Tokyo）
- 状態: `現行`

---

## 前提

- Python 3.13
- `uv`
- `bun`
- live利用時のnetwork接続

Private API keyは不要であり、追加しない。

## 標準起動

repo root:

```bash
bash scripts/start-all.sh
```

networkを使わない場合:

```bash
SNAPSHOT_SOURCE=fixture bash scripts/start-all.sh
```

保存済みsnapshotだけでWebを起動する場合:

```bash
SNAPSHOT_SOURCE=skip bash scripts/start-all.sh
```

既定URLは`http://127.0.0.1:5173/`。使用中なら5174以降の最初の空きportへ
自動fallbackし、実際のURLを`url=...`へ表示する。`PORT`指定値も探索開始値で、
開始値を含む最大100候補を昇順に調べる。選択後の競合raceは別portへ黙って移らず
停止する。終了は起動terminalの`Ctrl-C`。

## Service

```bash
cd apps/scanner-core
uv run watchdeck service
```

有限確認:

```bash
uv run watchdeck service --max-symbols 1 --stop-after-records 1
uv run watchdeck doctor
```

service実行中に同じDBへ別writerを起動しない。画面からのsnapshot更新は
`publish-service`経路を使う。

### 正式なuser systemd設定

正式なunit templateは`config/systemd/`、安全な生成・導入入口は
`scripts/ops/install-user-services.sh`である。通常の確認はdry-runで、unitを変更しない。

```bash
cd /home/tn/projects/prep-watchdeck
bash scripts/ops/install-user-services.sh --dry-run
bash scripts/ops/install-user-services.sh --check
```

`--check`は導入済みunitとrender結果が同一の場合だけexit 0になる。意図した差分を確認して
導入する場合だけ`--apply`を使う。

```bash
bash scripts/ops/install-user-services.sh --apply
```

applyは既存unitを同じdirectoryへ`.bak.<timestamp>.<pid>`として保存し、atomic replace、
`daemon-reload`、`enable`まで行う。service/Webをstart・restartしない。表示されたbackup pathは
rollback完了まで保持する。

serviceはSIGTERM時にbackground taskをcancel/gatherし、最終`service-state.json`だけを発行する。
既存のperiodic snapshotを正本として使い、終了時に重複したfull snapshotを新規生成しない。
live規模のfull snapshot実測に対し、進行中snapshotの安全な完了余裕としてservice unitの
`TimeoutStopSec`は90秒とする。通常の停止目標はin-flight snapshot時も60秒以内であり、
90秒は異常時のSIGKILLを避けるための上限であって、強制終了を通常の停止経路にしない。

DuckDBの`snapshots` tableはlatest cacheであり、履歴Archiveではない。save成功時に最新run 1件だけを
保持する。過去versionで蓄積した削除済みrowによりDB fileが肥大した場合は、全writerを停止し、
[DuckDB公式のreclaiming space手順](https://duckdb.org/docs/current/operations_manual/footprint_of_duckdb/reclaiming_space)
に従って新規DBへ`COPY FROM DATABASE`する。元/新DBの全table件数、column、constraintを照合し、
旧DBをrollback backupとして保持してから同一filesystem上で入れ替える。`VACUUM`をfile縮小手段として
扱わない。

service unitは通常の直近60本reconcileとは別に、74h判定に必要な5885本を低優先で構築する。

```text
--backfill-limit 0
--reconcile-concurrency 1
--ticker-refresh-interval-sec 60
--deep-backfill-limit 5885
--deep-backfill-batch-size 1
--deep-backfill-concurrency 1
--deep-backfill-cooldown-sec 5
--deep-backfill-retry-delay-sec 60
--deep-backfill-rate-limit-per-second 1
```

同じstate rootに別の`watchdeck service`を起動せず、full local gateとunit diff確認後に
正式unitを1回だけcontrolled restartする。deep backfillはrestart後も進捗を
`service-state.json`の`deepBackfill`へ出す。

### 更新停止watchdog

既定値:

```text
--watchdog-interval-sec 60.0
--watchdog-stall-sec 300.0
--watchdog-confirmations 3
--watchdog-startup-grace-sec 300.0
```

startup grace後、最新1分足timestampが300秒以上前進しない時だけBitget public candle
RESTを1銘柄・limit 1で確認する。REST正常下の停止が3回連続するとserviceは非0終了する。
timestampが前進した場合、またはREST probeが失敗・空responseとなった場合は連続確認を
resetする。したがってBitget側の障害中はserviceを落とさず、stale表示とWebSocket再接続を
継続する。

自動復旧させるprocess managerは`Restart=on-failure`でなければならない。user systemd
unitでは次を確認する。`WatchdogUSec=0`でもよく、`WatchdogSec` protocolは使用しない。

```bash
systemctl --user show prep-watchdeck-service.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts \
  -p Restart -p RestartUSec -p WatchdogUSec
```

`Restart=on-failure`でなければwatchdog検知後の自動復旧は行われない。systemdを使わず
terminalから起動した場合も、検知時は非0終了するだけで自動再起動しない。

### 確認とrollback

切替はfocused/full gateが成功し、unit dry-run差分を確認した後に1回だけ再起動する。
再起動前後でMainPIDを記録し、再起動後は次を確認する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
state_root="$(realpath -m "${PREP_WATCHDECK_STATE_DIR:-var}")"

systemctl --user show prep-watchdeck-service.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p Restart

jq '{generatedAtMs,dataAsOfMs,diagnostics,backfill,reconcile,deepBackfill}' \
  "$state_root/snapshots/service-state.json"

curl --fail http://127.0.0.1:5173/api/health
lsof "$state_root/watchdeck.duckdb"
```

MainPID変更、`active/running`、state/data timestamp前進、Web health、同じDuckDBへの
writerが1つだけであることを確認する。異常時はserviceの起動引数へ
`--watchdog-interval-sec 0`を追加して1回だけ再起動する。code自体を戻す場合は変更前commitへ
戻して1回だけ再起動する。DB migrationとschema変更はないため、state dataの逆変換は不要。
Bitget障害中に再起動を繰り返さない。

unit設定を戻す場合は、`--apply`が表示したservice/Webそれぞれのbackupを元のunit pathへ
`install -m 0644`で戻し、`systemctl --user daemon-reload`後に1回だけcontrolled restartする。
deep backfillがupsertした正常なpublic candleは削除しない。

serviceはbootstrap後もBitget public all-tickerを60秒ごとに1回取得し、`holdingAmount`と
provider `ts`をfreshなOI current sampleへ使う。取得失敗はwarningとして次cycleへ継続し、
private APIや古い値へのfallbackは行わない。

## State root

移行後は次でRepo外stateを選べる。

```bash
export PREP_WATCHDECK_STATE_DIR="$HOME/.local/share/prep-watchdeck"
```

未指定時はrepo `var/`を使う。個別path環境変数を指定した項目は、
その値がstate rootより優先される。
相対state rootはRepo root基準。通常運用では誤解を避けるため絶対pathを推奨する。

個別overrideはsnapshot、service state、ticker runtime、chart、Past Note、Dashboard settingsの
監視stateだけを対象とする。退役済みrecord directoryのoverrideが設定されている場合は、空値でも
起動をfail-closedにする。

起動scriptはstate root、DB、snapshot、service state、ticker runtime、chartの
絶対pathを表示する。scanner-coreとWebの個別overrideが不一致なら起動しない。

## 退役recordのArchiveとrollback証拠

Attack TicketとTrade Memoの旧source recordは、active state移行前にwriterをすべて停止して
Repo外へArchiveする。

```bash
bash scripts/maintenance/archive-retired-records.sh \
  --archive-dir "$HOME/watchdeck-local-archive/retired-records-$(date +%Y%m%d-%H%M%S)"
```

このcommandはJSON envelope、record件数、byte数、相対path SHA-256、copy前後のsource不変、
一時directoryへのrestore smokeを検証し、sourceを削除しない。後日再検証する場合:

```bash
bash scripts/maintenance/verify-retired-records-archive.sh \
  --archive-dir "$HOME/watchdeck-local-archive/retired-records-YYYYMMDD-HHMMSS"
```

検証失敗時はactive state移行へ進まず、sourceとArchiveの双方を保持する。Archiveはproductionへ
直接mountせず、旧機能を復元する場合も新しいADRと明示的なrestore/migrationを先に用意する。

## State移行

service、scan、Webを停止してから実行する。

```bash
bash scripts/maintenance/migrate-state-dir.sh \
  --target "$HOME/.local/share/prep-watchdeck" \
  --archive-dir "$HOME/watchdeck-local-archive/state-$(date +%Y%m%d-%H%M%S)"
```

旧`var/`全体はfull Archiveへcopyし、active state layout v2だけを新rootへcopyする。

```text
watchdeck.duckdb
watchdeck.duckdb.wal（存在する場合）
snapshots/
past-notes/
dashboard-view-settings/
usage-events/
ops/
```

旧`data/scanner.duckdb`が存在する場合は`legacy-data/`へcopyする。sourceは削除しない。
Archiveの`STATE_LAYOUT_VERSION`へ`2`を記録し、source全体とactive filesのmanifest/SHA-256を記録して、
sourceとArchiveのfile list・hashを完全一致で検証する。source、target、Archiveが同一または
親子pathの場合、target/Archiveが非空の場合、v2 targetへ旧record fileが混在する場合は停止する。
version markerがない既存Archiveはlayout v1として引き続き検証し、未知versionは拒否する。

切替後:

```bash
export PREP_WATCHDECK_STATE_DIR="$HOME/.local/share/prep-watchdeck"

bash scripts/maintenance/verify-state-dir.sh \
  --source "$PWD/var" \
  --target "$PREP_WATCHDECK_STATE_DIR" \
  --archive-dir "$HOME/watchdeck-local-archive/state-YYYYMMDD-HHMMSS" \
  --mode cutover
```

`cutover`検証は旧stateがcopy時点から変更されていないこと、新rootに移行対象が
残っていること、Past NoteとDashboard settingsの件数が減っていないこと、JSONと
snapshot/chart runIdが有効なことを確認する。

rollbackではservice、scan、Webを停止し、新rootのwriterが0であることを確認してから
`PREP_WATCHDECK_STATE_DIR`を以前のrootへ戻す。旧sourceとfull Archiveは削除・上書きしない。
Archiveから復元する必要がある場合は、既存targetへmergeせず、新しい空directoryへ復元して
manifest/SHA-256を再検証してから切り替える。

## Test state

E2E、performance、soakは現役stateを使わず、次へ隔離する。

```text
$PREP_WATCHDECK_STATE_DIR/tmp/e2e/runtime
$PREP_WATCHDECK_STATE_DIR/tmp/performance/runtime
$PREP_WATCHDECK_STATE_DIR/tmp/soak/runtime
```

`PREP_WATCHDECK_STATE_DIR`未指定時だけrepo `var/tmp/`へfallbackする。

test runtimeはDB、snapshot、Past Note、Dashboard settingsだけを必要に応じて作り、退役record用の
directoryを作らない。

## 日次サマリー

```bash
bun scripts/ops/watchdeck-daily-summary.mjs
```

schema v2はusage events、snapshot、Past Note、Dashboard settingsだけを読み、
`$PREP_WATCHDECK_STATE_DIR/ops/daily/v2/`へ出力する。過去のschema v1 fileは上書きしない。

## 旧文書Archive

```bash
bash scripts/maintenance/archive-repo-history.sh \
  --archive-dir "$HOME/watchdeck-local-archive/repo-history-$(date +%Y%m%d-%H%M%S)"
```

相対path hashとmanifestを検証し、sourceを残す。`VERIFIED`がないArchiveを根拠に
Git追跡を外さない。

追跡解除直前:

```bash
bash scripts/maintenance/verify-repo-history-archive.sh \
  --archive-dir "$HOME/watchdeck-local-archive/repo-history-YYYYMMDD-HHMMSS"
```

この再検証は、Archive時点からtracked対象が増減していないこと、sourceが変更されて
いないこと、Archive本体が記録済みhashと一致することを確認する。1つでも不一致なら
旧文書とmockupを削除しない。

Repo history Archiveとstate Archiveの両方が揃った後:

```bash
bash scripts/maintenance/finalize-reorganization.sh \
  --repo-history-archive "$HOME/watchdeck-local-archive/repo-history-YYYYMMDD-HHMMSS" \
  --state-target "$HOME/.local/share/prep-watchdeck" \
  --state-archive-dir "$HOME/watchdeck-local-archive/state-YYYYMMDD-HHMMSS"
```

既定はdry-run。Repo history、state cutover、legacy DBの全証拠を再検証する。
dry-run成功後にだけ`--apply`を追加する。削除対象は検証済みmanifestの旧文書・
mockupと検証済み`data/scanner.duckdb`だけで、旧`var/`はrollback用に保持する。

`--apply`は最初の削除より前にRepo history Archive内へ一時証跡を作成する。
Archiveへ作成・書込みができなければ削除0件で停止する。正常完了時は
`REPO_FINALIZATION_VERIFIED`へ確定する。削除開始後の失敗で
`.REPO_FINALIZATION_VERIFIED.*`が残った場合は削除せず、部分実行の照合に使う。

## 検証

```bash
bash scripts/verify-local.sh
```

UI変更時:

```bash
cd apps/web
bun run check
bun run test
bun run build
```

## 停止条件

- DuckDB lockを検出した。
- snapshotとchartのrunIdが一致しない。
- old/new state pathの両方が更新される。
- Past Note、Dashboard settings、source全体、Archiveの件数・file list・hashが一致しない。
- layout v2 targetへ退役record fileが混在する。
- Webがscanner-coreと異なるstate rootを表示する。

この場合は旧stateを削除せず、環境変数を外してrepo `var/`へ戻す。

## OI sample運用

`watchdeck service` startup時に`open_interest_samples`をadditive初期化する。DDL/init失敗は
serviceを起動済み扱いにしない。各snapshot cycleのOI保存・読込・prune失敗はsnapshot発行を
継続するが、`summary.oiDiagnostics`をdegradedにし、全OIを`UNKNOWN`として加点しない。

OI sampleはsource時刻の5分bucketで24時間だけ保持する。service再起動後は同じstate rootの
履歴を再利用する。同一DuckDBへ別writerを起動しない既存運用を維持する。
