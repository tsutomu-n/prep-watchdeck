# prep-watchdeck 現行運用

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
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

## 独立ランキングの起動・停止・復旧

ランキングは独立した公開データcollectorとSQLiteを使う。元のMarket Core、Postgres、artifactへ
書き込まず、既存serviceの環境変数やDB接続情報を引き継がない。確認済みの固定参照契約だけを取得する。
現mapの原資産・固定参照の全件gateは成立し、534参照を採用する。元数量換算とWidgetは各3件未確認。
`--require-ranking-qualified`は成功するが、数量・Widgetも要求する`--require-reviewed`は終了1となる。
行の要確認・未対応・対象外は名簿に残し、数値を生成しない。
対応表の更新方法は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core/data/README.md](../../apps/ranking-core/data/README.md)を参照する。

隔離した確認用の起動例。指定したstateだけを新規作成し、書込み可能にする。
`bwrap`が利用できない場合は開始しない。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117
uv sync --frozen
uv run --package prep-watchdeck-ranking python scripts/ranking/run-isolated.py \
  --mapping /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core/data/initial-map.json \
  --state-dir /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/var/tmp/ranking/manual \
  --original-state-dir /home/tn/.local/share/prep-watchdeck-market \
  --port 18769 \
  --run-seconds 900
```

| 入力・操作 | 起きること | 次へ進める条件 |
| --- | --- | --- |
| 上記command | 公開catalogを確認し、保存済み履歴を再利用して不足分を補完する。起動直後は準備中または履歴不足を返す。 | `/health`にgenerationがあり、必要な比較期間の有効数が対応数と一致する。 |
| Webに`PREP_WATCHDECK_RANKING_PORT=18769`を設定して別portで起動 | `/rankings`がloopbackの専用APIから結果を読む。Browserによる外部価格取得は増えない。 | 比較時刻、対応数、参照契約、順位の方向を確認できる。 |
| foregroundでCtrl+C、または指定時間の経過 | 当該collectorとAPIだけが終了する。SQLiteと証拠は残る。 | 別processの元収集は継続する。 |
| 同じstateとmapで再起動 | 欠けた確定1分足をRESTで補完し、WSを再購読する。 | 同じ契約の履歴がそろうまで不足表示を維持する。 |
| mapの参照契約を変更して再起動 | 新しいreference revisionを別の履歴として扱う。 | 新契約の履歴がそろってから順位へ戻る。 |

保存先の同一・内包・symlinkを起動前に検査し、SQLite関連fileのsymlinkも拒否する。
起動wrapperはhost filesystemを読取り専用、専用stateだけを書込み可能にし、環境を最小化する。
直接`watchdeck-ranking serve`を呼ぶ場合、source上の検査は働くがOSの書込み制限は付かない。
通常の手動起動にもwrapperを使う。

各Providerはcatalog取得も含めREST 2 request/秒・同時2、WS最大3接続、接続再試行上限60秒、履歴約48時間、
現在と直前1世代それぞれにHH:mm別cache 32件。全体1,500参照契約を超えるmapは再測定を要する。通常は分境界8秒後に
発行し、処理が12秒を超えた世代は公開しない。150秒以上古い比較結果は更新停止表示になる。
初期履歴不足、取得停止、catalog変更、古い名簿はそれぞれ別の状態として示す。

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/config/systemd/prep-watchdeck-ranking.service.in](../../config/systemd/prep-watchdeck-ranking.service.in)
は未installのtemplateであり、既存installerには組み込まれていない。placeholderを実効pathへ解決して
内容を確認した後、unitのinstall・enable・startは別途承認された操作として行う。
templateの上限はMemoryMax 768M、CPUQuota 100%、TasksMax 32、LimitNOFILE 128。
手動試験へこのcgroup上限を適用したとは扱わない。

独立ランキングを切り離す場合は、そのcollectorを停止し、WebのUniverse Explorerを使う。
元DBのmigration・rollback・既存unitの変更は必要ない。stateや未commitの差分を自動削除しない。


### 初回準備と再開を区別する

| 入力・操作 | 起きること | 次へ進める条件 |
| --- | --- | --- |
| 空の専用stateで制限付き起動する | 最初の世代までは準備中。その後、契約ごとに24時間分の確定足を補完する。 | 対応数を縮めず、有効数と各行の履歴不足の減少を確認する。新規上場等で必要な履歴自体がない場合は不足を維持する。 |
| 正当な保存済みstate・同じmapで同じ専用processを起動する | 既存OHLCを読み、不足分だけを補完する。旧snapshotを発行済み順位の比較元へ復元しない。 | 初回の順位変化は「比較不可（初回・再起動後）」、直前の分の世代がそろった次回以降に比較する。 |
| 画面で更新停止を確認する | 比較時刻が残る。今回または前回の比較時刻から150秒超なら順位変化も比較不可になる。 | 専用APIのhealth・Providerのlast_error・backfill_pendingを確認し、該当する専用processだけを復旧する。 |
| APIは動作中だが履歴不足が続く | 確定足の欠測、取得制約、履歴準備、上場直後などを示す。 | 同じ参照契約の履歴を確認する。別Providerで補完したり、欠測を0へ変更したりしない。 |
| reference_invalidが現れる | 公開catalogの廃止・revision変更を検出した参照契約を無効化する。 | 下記の候補mapを全件照合し、承認された専用process再起動で反映する。 |

### 名簿と参照revisionを更新する

元のUniverse snapshotはidentity入力として読み取るだけで、既存DBへ接続する必要はない。
最初に利用するsnapshotの絶対パス、生成時刻、取得成功・部分失敗の状態を確認する。取得失敗で
名簿が縮んだsnapshotを、正式な取扱い削除として採用しない。

| 入力・操作 | 起きること | 次へ進める条件 |
| --- | --- | --- |
| `watchdeck-ranking export-roster`へ確認済みsnapshotの絶対パスを渡し、標準出力を新しい候補先へ保存 | 元のinstrument ID・version・取扱いidentityを抽出する。起動中のmapは変更しない。 | 旧名簿との追加・削除・version差を列挙でき、部分取得と実際の上場変更を区別できる。 |
| 元IDを保持した候補decisionsと一次根拠、Widget metadataを作成する | 原資産・固定参照契約を確定し、元数量換算・Widgetの対応を別に記録する。参照revision変更は別履歴になる。 | 全対象の取扱いに根拠があり、原資産・固定参照の要確認がない。残る数量・Chart未確認と制限を明示できる。 |
| `compile-map --roster`と`--decisions`へ候補の絶対パスを渡して新しいv2 mapを出力する | 名簿のID/version・fingerprintと判断の整合を検査する。v1は暗黙変換しない。 | `validate-map`の`--require-ranking-qualified`が終了0となり、証拠checkerの内容監査も成立する。 |
| 候補directoryにinitial-roster.json、initial-map.json、qualification-evidence.jsonをそろえて`verify-map-evidence.py --directory`で照合する | 全original、revision、Widget、行・数量の未解決台帳を照合する。 | map versionと根拠が一致し、`rankingQualified`がtrue。数量・Widgetも全確認する場合は`--require-reviewed`と`qualificationComplete`を使う。checker成功と根拠の正当性を別に監査する。 |
| 旧map/sourceの所在を保全し、反映対象を確定して専用processだけ再起動する | 再起動時に新mapを採用し、新revisionの履歴不足は明示する。 | 新map version・対応件数・鮮度・参照Chartを実際のAPIと画面で確認する。稼働unitの場合は別承認を得る。 |

削除した契約は新mapの参照対象から外れ、通常の専用stateの保存整理の対象になる。
追加指標の導入自体は表・保存形式・保存期間を変更しない。旧revisionの履歴を新revisionへ
つなぎ直さない。旧mapへ切り戻す場合に整理済み履歴が不足すれば、同じ旧契約の公開APIで補完する。

### 追加機能を切り戻す

ランキング用API・Web・生成schema/型を一組として、検証した同じsource版へ戻す。
SQLiteの表は共通だが、APIのschemaVersion・metricVersionと必須fieldが異なる場合があるため、
片側だけを戻すとWebは形式不一致として取得待ちになる。必要なsource/mapを別の場所に保全し、
既存の未commit差分を上書きしない。切戻し時も専用collectorの停止・再開以外に元DBの操作を加えない。
