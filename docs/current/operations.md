# prep-watchdeck 現行運用

timestamp="2026-10-05(月)_17:52 JST"
- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-10-05T17:52:40+09:00`
- 検証: `2026-10-05T17:52:40+09:00`
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

Markets workspaceを配置する場合はMarket Core、Ranking Core、Webの契約を同じ検証済みsource組で切り替える。追加の`market-metrics.json`は任意laneで、旧4 artifactへ混ぜない。NoteFile v2を一度書いた後に旧Webへ戻す際は、対象stateを別場所へ退避して旧版用の状態を復元する必要がある。旧Webがv2を安全に読めると仮定して元ファイルへ上書きしない。稼働releaseへの反映はunitの実効WorkingDirectoryと配置sourceのcommitで照合する。実データの180秒lag/300秒上限の受入は配置・Web healthとは別に確認する。

開発branchのmetrics投影は専用lockでwriterを排他し、JSON破損または既知schemaの検証破損に限って、正常なDB snapshotから再生成する。破損原本はartifact directoryの`market-metrics.json.corrupt-<id>`へbyte単位で退避・fsync・readbackし、元ファイルが変わっていないことを再確認してatomicに置き換える。未知schema/metricVersion、読取権限、保全失敗、並行変更、lock競合では更新を停止してworkerがerrorTypeを記録する。保全物は自動削除しない。これは派生metrics専用の復旧であり、メモの破損保護を緩めない。

metrics workerは投影ごとに子processを1つだけ起動し、DB接続・投影・破損保全・発行の処理を10秒で打ち切る。timeoutでは子processをkill・回収してから次を処理し、停止時も進行中処理を待つ。DBのstatement上限5秒・transaction上限8秒・接続上限2秒も維持する。process起動時のDB資格は標準入力に渡し、command lineや例外logへ載せない。OS停止などを含む厳密な応答時間保証ではない。

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

### スマホからの接続

Webのlistenerは`127.0.0.1:5173`を維持し、既存Tailscale ServeのHTTPS proxy経由で接続する。
スマホは許可されたtailnetへログインして接続する。このhostの既存URLは
`https://ubuntu.narluga-gecko.ts.net:8444/`。スマホ本人による接続確認はserver検証と別に行う。

Web unitに`PREP_WATCHDECK_TRUSTED_TAILSCALE_ORIGIN=https://ubuntu.narluga-gecko.ts.net:8444`を
指定する。Viteの既存allowed host設定も保持する。設定したoriginとloopbackのproxy接続に加え、
Serveの認証済みuser identity headerが揃った場合にlocal APIを利用できる。

タグ付き端末にはuser identity headerが付かないため、このサーバー自身から同じHTTPS URLを開く場合は
別途自端末を確認する。proxyが付けたHTTPS・Host情報と単一の接続元IPを確認し、local tailscaledの
read-only status / WhoIsで、Running状態、設定hostとSelfのDNS、接続元とSelfのIP、WhoIsのStableIDと
Self IDが一致するタグ付き自端末だけを許可する。問い合わせ先は
`/var/run/tailscale/tailscaled.sock`のUnix socketに固定し、外部API、CLI実行、追加credentialを使わない。
socketが読めない、timeout、不正response、別端末、Funnel経由の場合は拒否する。
タグ付き端末全体を許可する設定ではない。

JSON更新には引き続き設定したHTTPS originとの一致が必要。検証時にidentity headerを手作業で付けて
認証成功と扱わない。serverからのHTTP・ブラウザー検証と、スマホ実機での本人操作確認を分ける。
URL変更時はこのoriginとVite allowed hostを一組で更新する。Tailscale ACLやFunnelを自動で変更しない。

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
現mapの原資産・固定参照の全件gateは成立し、536参照を採用する。元数量換算とWidgetは各3件未確認。
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

各Providerはcatalog取得も含めREST 2 request/秒・同時2、WS最大3接続、接続再試行上限60秒。
履歴は4日と1分を保持し、起動時と欠落回復時は3日分と価格境界の4,321本を補完する。
1契約のREST履歴取得は1,000本ずつ最大5ページで、rate limitとbackoffは維持する。
現在と直前1世代それぞれに応答cache 8件、HH:mm別の期間計算cache 8件を保持する。
3日分の数値は変更不能なコンパクト配列で固定する。全体1,500参照契約を超えるmapは再測定を要する。通常は分境界8秒後に
発行し、処理が12秒を超えた世代は公開しない。150秒以上古い比較結果は更新停止表示になる。
初期履歴不足、取得停止、catalog変更、古い名簿はそれぞれ別の状態として示す。

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/config/systemd/prep-watchdeck-ranking.service.in](../../config/systemd/prep-watchdeck-ranking.service.in)
は専用unitのtemplateであり、既存installerには組み込まれていない。placeholderを実効pathへ解決して
内容を確認した後、unitのinstall・enable・startは別途承認された操作として行う。
templateの上限はMemoryMax 768M、CPUQuota 100%、TasksMax 32、LimitNOFILE 128。
手動試験へこのcgroup上限を適用したとは扱わない。

独立ランキングを切り離す場合は、そのcollectorを停止し、WebのUniverse Explorerを使う。
元DBのmigration・rollback・既存unitの変更は必要ない。stateや未commitの差分を自動削除しない。


### 初回準備と再開を区別する

| 入力・操作 | 起きること | 次へ進める条件 |
| --- | --- | --- |
| 空の専用stateで制限付き起動する | 最初の世代までは準備中。その後、契約ごとに3日分と価格境界の確定足を補完する。 | 対応数を縮めず、有効数と各行の履歴不足の減少を確認する。新規上場等で必要な履歴自体がない場合は不足を維持する。 |
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

`scripts/ranking/refresh-roster-candidate.py`は、確認済みの完全snapshot・現行定義のread-only
監査・最新official catalog・明示した新規判断を使い、別directoryへ更新候補を作る。
既存の採用済み参照provider/revisionを固定し、identityが変わった場合や新規銘柄の根拠が
足りない場合は拒否する。live mapやサービスを自動変更しない。引数は`--help`で確認し、
出力候補へ上記のmap/evidence検査を適用する。日付だけの更新で名簿の古さを隠さない。

削除した契約は新mapの参照対象から外れ、通常の専用stateの保存整理の対象になる。
過去日比較の導入では表・保存形式を変えず、保存期間を4日と1分へ延長する。旧revisionの履歴を
新revisionへつなぎ直さない。旧mapへ切り戻す場合に整理済み履歴が不足すれば、同じ旧契約の公開APIで補完する。
新しい版の初回は過去日が欠けていても、現在の順位条件がそろえば順位を表示し、過去日比較だけを
履歴不足にする。初期充足時間・実Provider負荷・稼働hostでの容量は別途実データで受け入れる。

### 追加機能を切り戻す

ランキング用API・Web・生成schema/型を一組として、検証した同じsource版へ戻す。
SQLiteの表は共通だが、APIのschemaVersion・metricVersionと必須fieldが異なる場合があるため、
片側だけを戻すとWebは形式不一致として取得待ちになる。必要なsource/mapを別の場所に保全し、
既存の未commit差分を上書きしない。切戻し時も専用collectorの停止・再開以外に元DBの操作を加えない。
`ranking-v4`の過去日比較を読むWebは同じ契約のRanking Coreと組み合わせる。表のmigrationは不要。
保持期間が短い旧版のcollectorへ戻すと、追加取得した古い足は旧版の通常pruneで削除される。

### 通常稼働への配置記録

2026-09-16にPR #15をmergeし、main CIが成功した`d1c44d5c3e57a1b75421e35284248a9c1257a871`を
`/home/tn/releases/prep-watchdeck/d1c44d5`へ配置した。D05の通常稼働・再開・切戻し受入はPASS。
これは当該host・観測時点の記録であり、将来の稼働versionはunitの実効WorkingDirectoryで確認する。

- `prep-watchdeck-ranking.service`: enabled/active、127.0.0.1:8769、専用stateは
  `/home/tn/.local/share/prep-watchdeck-ranking`。元Market state・Postgresへ書き込まない。
- `prep-watchdeck-web.service`: 127.0.0.1:5173、配置版のWebを既存のdev起動commandで稼働する。
  `/home/tn/.config/systemd/user/prep-watchdeck-web.service.d/ranking-chart-release.conf`で
  WorkingDirectoryとランキングportだけを指定する。Market state・Tailscale host設定は保持した。
- 実cgroupはmemory.max=805306368、cpu.max=100000 100000、pids.max=32。
  実collectorのファイル記述子上限は128、hostはread-only、専用stateはread-writeである。
- Market Core・DB・maintenanceのunit設定を変更せず、Market CoreのPID・起動時刻の継続を確認した。

切戻しでは上記追加drop-inだけを外し、daemon-reloadとWeb再起動で
`/home/tn/releases/prep-watchdeck/dc2a8d7/apps/web`へ戻す。ランキングunitを停止し、stateを保持する。
実際に旧UniverseのHTTP 200・旧WorkingDirectory・ランキング停止を確認した後、
ランキングの再起動と全件受入を経て追加drop-inを再適用し、配置版の画面を再確認した。

元数量換算とWidgetの各3件は未確認を維持する。名簿は固定の審査済みsnapshotであり、
24時間経過後の「取扱い名簿の更新が止まっています」は仕様どおり表示する。現在の全上場銘柄を
自動追随したことや、全Widgetの個別描画を確認したことを、この配置結果から主張しない。
詳細な検証結果は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/docs/current/validation.md](validation.md)を参照する。

## 表示用ロゴの追加・更新

ロゴはWeb内の表示用manifestとローカル画像から配信し、画面表示時に外部画像APIへ問い合わせない。
市場収集・契約version・ランキング資格・数量倍率・参照provider・Widget対応は変更しない。

追加時は採用済みmapの原契約ID/versionと原資産を確認し、正式な画像出典・保存/再配信条件・
credit・未改変/変更内容・SHA256を`apps/web/src/lib/assets/asset-logos.json`へ記録する。
同名symbol、1000等の文字列から画像を推測しない。未確認の素材を採用して全件を埋めない。
素材の初期採用はBitPayのBitcoin icon（CC0）とMonero公式Symbol（CC BY-SA 4.0）。
各出典・credit・ライセンスは`apps/web/static/asset-logos/credits.html`から確認できる。
CoinGeckoのAPI画像は、保存・更新・再配信条件に適合する運用を導入していないため未採用。

Repo rootで`bun scripts/assets/generate-logo-bindings.mjs`を実行し、画像のSHA256・静的形式・
利用条件記録・map/evidenceの一致を検査して、確認済みassetの原契約ID/versionだけを生成する。
`--check`は生成物との一致確認。mapを更新した場合も再生成・差分確認・Web検証を行う。
新しい版が未照合の場合は中立表示になり、古い画像対応をsymbolから引き継がない。
このcommandはmap/evidenceを読み、Webの表示用bindingだけを書き、runtime DB/stateへ作用しない。
画像が読めなくても通常の一覧・選択・お気に入りを使え、同じ枠サイズ・行位置を維持する。

## 保存足の回収・照合・比較・出力

このRepositoryで実装済みの操作手順。稼働releaseへの配置、設定変更、本番DBへの適用、
実Provider keyの使用は別の承認・受入で扱う。初回は隔離DBと専用state rootで実行する。

`apps/market-core/`で`uv run watchdeck-market recover-candles --instrument <ID> --since <ISO> --until <ISO> --json`
を実行するとscanのみを返す。期間を省略すると確定済みの直近6時間を調べる。
許可済み対象への`--apply`はnative履歴を取得し、欠損だけ挿入する。現行契約の版・定義hashが変わったら
対象を停止する。自動実行は`PREP_WATCHDECK_CANDLE_RECOVERY_ENABLED=true`を明示したserviceだけで有効。
falseに戻しても追加済みの正当な保存足を自動削除しない。

有効なserviceでは15分ごとの履歴回復に加え、毎分の不足endpoint回復が動く。
後者は各対象の取得直前にcutoffを再確認し、現在・15分・1時間・24時間の必要足を
公式native履歴から回収する。Hyperliquidの現在終点が欠測の銘柄だけは、形成中を除いた直近の確定済み3本も
同時に欠損確認・保存し、次の指標cutoffで補修待ちを減らす。先取りだけが不足する
銘柄は補修queueへ入れず、実際の指標欠測を優先する。Bitget・Asterは従来の必要足を
維持する。Providerが実際に返した確定足だけを扱う。180秒のgraceは指標cutoffの
猶予であり、Hyperliquidの先取り保存に180秒を追加で待つ指定ではない。最大20 HTTP request・60秒・最低3秒間隔で、未処理対象は
次runへ順番に送る。現在の終値、15分・1時間の基準、24時間の基準の順に処理し、
各優先度で公平な再開位置を保持する。直近の取得に24時間前の範囲を混ぜず、
過去側の不正応答が先に保存した現在の足を失わせない。各範囲は最大1page。
通常履歴は既定5秒間隔・自動120 request上限を維持する。
HTTP応答は8MiB上限と既存timeout内でEOFまで受信する。分割到着したJSONを
途中で解析しない。過大応答、重複key、非有限値、identity不一致等は引き続き拒否する。
近い不足endpointは1つの取得範囲へまとめるが、保存するのは事前確認した不足行だけ。
取引数0でもProviderが返した正当な足は保存し、Providerが返さない時刻の足は作らない。
新version開始前の基準足は旧版から付け替えず、履歴が成立するまで欠測を維持する。
Endpoint回復の対象別エラーは`collector_runs.metrics.targetErrors`へ最大128件を保持する。
銘柄ID・version・安全なerrorCodeだけを残し、後続runによるartifact更新後も確認できる。
`priorityRequests`で優先度別のHTTP request数を記録する。指標の`lastTargetCutoff`と
保存可能な足のexclusive endである`lastClosedWindowEnd`を分け、監査windowは保存対象を覆う。
Bitget取得失敗のservice logにはHTTP statusを残し、URL・応答本文を出さない。

HyperliquidのWebSocket候補はprocess内のメモリに保持し、足終了5秒後に`derived_final`として
保存する。同一process内の再接続では候補を保持するが、process停止時は未保存候補を失うため、
再起動前後の足が一時的に欠測になる場合がある。5秒の確定判定と180秒の指標cutoff猶予を
混同しない。自動回復は不足足を再取得するが、取得予算内で即座に全件回復する保証はない。
再起動後はhealthの成功だけで完了とせず、複数cutoffの指標件数と回復監査を確認する。

Bitgetの確定足pollは120秒周期・同時4 requestを維持し、各request時刻で終了時刻を決めて
直近8本を保持する。注文上限だけのcatalog変更で不要に版を更新することも避ける。
実際の価格・数量単位・上場定義の変更は引き続き新versionとして扱う。
Asterの上場境界`onboardDate`を確認できる`PERPETUAL`では、`createTime`だけの変動で
履歴を区切らない。上場境界が変わる場合や確認できない場合は版を分ける。
上場境界の原文定義は[公式Aster Exchange Information](https://asterdex.github.io/aster-api-website/futures-v3/market-data/#exchange-information)を参照する。

### 定期的にデータ運用を確認する

`scripts/market/check-data-operations.py --market-state-dir <絶対state path> --mapping <絶対map path> --json`
はartifactとloopback Ranking healthだけを読み、取得・DB更新・map採用を行わない。
更新停止、収集失敗、現行UniverseとmapのID/version不一致は終了1、不正入力は終了2。
銘柄履歴の不足、取得予算の未処理、24時間を過ぎた名簿は警告として件数・理由を残す。
価格・秘密情報・個人メモをlogへ出さない。

`config/systemd/prep-watchdeck-data-operations.service.in`と対応timerはread-only確認の任意template。
`@REPO_ROOT@`を検証済みrelease、`@MARKET_STATE_ROOT@`を専用stateへ置換してuser unitへ
配置した場合だけ、timerを明示的にenable/startする。5分ごとに確認し、結果は
`journalctl --user -u prep-watchdeck-data-operations.service`で読む。
timer停止は監視だけを止める。回復を止める場合は上記の有効化設定をfalseへ戻す。

自動600秒・手動4時間の上限は事前scanと取得後rescanにも適用する。上限後は新しい検査を開始せず、
未検査の欠損件数は`null`と記録する。進行中のDB処理はstatement timeoutの範囲で終了を待つ。
HTTP timeoutは残りrun時間以下とする。429の妥当な`Retry-After`（1〜86,400秒）は同じprocessの
次runにも保持し、値がない場合は900秒のVenue別cooldownを使う。

保存snapshotの比較は`apps/market-core/`で
`uv run python -m prep_watchdeck_market.candle_audit_publication --request <request.json> --state-dir <state-dir>`。
requestは`schemas/audit-request.schema.json`を満たす2入力のローカルpathを含む。
差異/不足でexit 1、比較不能でexit 3でもreportが発行される。入力不正は2、入出力・lock・容量障害は4。
過去runは上書きせず、index破損時は発行を停止する。

OpenMarket照合は事前に現在のnative契約を確認し、`OPENMARKET_API_KEY`をprocess環境から渡す。
`watchdeck-market reference-markets --venue <VENUE> --symbol <SYMBOL> --output <metadata.json>`で
候補を得る。対応を自動確定せず、`schemas/reference-mapping.schema.json`に従ってexact契約と
metadata hashを記録する。その後`watchdeck-market reference-snapshot --mapping <mapping.json> --since <ISO> --until <ISO> --output-dir <DIR>`で
1分の半開窓を取得する。結果の`reference.snapshot.json`はAuditの右入力へ渡せる。
key不在・不対応契約を他のVenueで代用しない。

Core用の固定証拠は`watchdeck-market export-fixture --instrument <ID> --version <整数> --since <ISO> --until <ISO> --output-dir <DIR>`。
`watchdeck-market verify-fixture --bundle <DIR/runId>`はDB/networkなしで整合性を再検査する。
`--audit-run <runId>`指定時だけ監査reportを添付する。fixtureとReferenceの出力はローカルに保持し、
公開・自動送信しない。出力失敗や部分完了を空datasetの成功と扱わない。

切戻し時はRecoveryの有効化を止め、進行中taskの終了を確認して旧release・設定を復元する。
監査run、Reference bundle、Fixture bundleを自動削除しない。Recoveryで追加した行の削除は
run_idを特定した別の修復判断とする。本番でのbackup、exact sourceの配置、実ProviderとUIの確認は
[作業計画](../plans/active/prep-quality-completion/GOAL.md)の受入台帳を通して行う。
