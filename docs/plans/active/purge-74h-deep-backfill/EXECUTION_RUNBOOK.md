# 74時間判定・deep backfillパージ実行手順書

- 作成: `2026-08-12T17:03:31+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 状態: `実装計画`

---

## 1. 実行原則

- 正本計画は[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)。このrunbookより現行Repoを優先する。
- 実装はCP-00から順に行い、各checkpointのfocused testが成功するまで次へ進まない。
- TDDは契約を直接固定する最小caseだけにする。既存testで証明できる場合は重複testを作らない。
- 既存の未コミット変更をreset、stash、checkout、整形、上書きしない。
- production DBの削除・migration・VACUUM、別writer、秘密API、注文機能を追加しない。
- `.codex/SP_STATE.md`は最初のCPだけを対象にする。CP完了時に次CPへ更新し、一度に全fileを
  AllowedFilesへ入れない。
- push、PR、merge、service restartは、メインスレッドの現行承認がある場合だけ行う。

## 2. CP-00: 開始前確認

canonical Linux checkoutを優先する。

```bash
cd /home/tn/projects/prep-watchdeck
git status --short
git branch --show-current
git rev-parse HEAD
git log -5 --oneline --decorate
git diff -- scripts/ops/install-user-services.sh scripts/start-all.sh \
  scripts/start-local.sh scripts/update-live.sh scripts/verify-local.sh
sed -n '1,260p' AGENTS.md
sed -n '1,320p' docs/plans/active/purge-74h-deep-backfill/IMPLEMENTATION_PLAN.md
sed -n '1,320p' docs/plans/active/purge-74h-deep-backfill/EXECUTION_RUNBOOK.md
```

Windowsの`U:`から確認する場合、global Git設定を変更せずper-commandでsafe directoryを指定する。

```powershell
$repo = '//100.105.132.102/tn-home/projects/prep-watchdeck'
git -c safe.directory=$repo status --short
git -c safe.directory=$repo branch --show-current
git -c safe.directory=$repo rev-parse HEAD
```

開始条件:

1. 現行Perp比較を含むHEADがbaseである。
2. Windows viewの5 script差分が`100755 → 100644`だけであることを確認し、canonical Linuxで内容差分が
   ないことを再確認した。
3. 今回のdocs以外に所有不明の差分を増やしていない。
4. source変更前の連続3 snapshotについて、取得可能なCPU、RSS、snapshot間隔、row数、chart file数を
   記録した。取得不能な値は理由とともに未確認とした。
5. 新branch名は`ai/purge-74h-deep-backfill-YYYYMMDD-HHMM`を使う。

停止条件:

- `ad3364f`以後のHEAD差分を計画へ反映できていない。
- canonical Linuxでscript内容差分が見つかり、今回のtestまたは編集と衝突する。
- current Perp比較commitを含まないbranchから開始しようとしている。

### 2.1 変更前の最低限計測

計測は現行serviceをrestartせず、同じMainPIDについて行う。`state_root`はsystemd unitのEnvironmentと
[`docs/current/operations.md`](../../../current/operations.md)から解決し、推測したpathを使わない。

```bash
service_pid="$(systemctl --user show prep-watchdeck-service.service -p MainPID --value)"
systemctl --user show prep-watchdeck-service.service \
  -p MainPID -p ActiveState -p SubState -p NRestarts -p Environment
ps -p "$service_pid" -o pid=,%cpu=,rss=,etime=,cmd=

# 利用可能なら180秒のCPU/RSS推移を取る。未導入ならinstallせず、psのpoint sampleだけを未精密値として残す。
command -v pidstat >/dev/null && pidstat -r -u -p "$service_pid" 1 180

# resolved state_rootへ置換する。
state_root='<resolved-state-root>'
for _ in 1 2 3; do
  jq '{runId,generatedAt,dataAsOf,snapshotStatus,rows:(.rows|length),perpItems:(.summary.perpVenueComparison.items|length)}' \
    "$state_root/snapshots/latest.json"
  find "$state_root/snapshots/charts/latest" -maxdepth 1 -type f -name '*.json' | wc -l
  sleep 65
done
```

`generatedAt`差はsnapshot公開間隔であり、build durationではない。現行codeにbuild duration計測はないため、
この計画で推定しない。必要ならruntime後の独立P1で計測点を追加する。

## 3. CP-01: 常駐deep backfill切断

### 3.1 RED

次の契約だけを既存testへ追加・更新する。

- service CLI helpに`--deep-backfill-*`がない。
- runtimeはdeep backfill task/providerを生成・cancel/awaitしない。
- `service-state.json` producerとWeb parserは`deepBackfill`を現行fieldとして要求・優先表示しない。
- systemd templateにdeep backfill optionがない。
- direct `service_deep_backfill.py` testは引き続き成功する。

対象test:

```text
apps/scanner-core/tests/test_service_runtime.py
apps/scanner-core/tests/test_service_state.py
apps/scanner-core/tests/test_service_deep_backfill.py
apps/web/src/lib/service-state.test.ts
scripts/ops/install-user-services.test.mjs
```

### 3.2 GREEN

次をproduction経路から削除する。

```text
apps/scanner-core/src/prep_watchdeck/interfaces/cli.py
  - DeepBackfill import
  - serviceの6個の--deep-backfill-* option
  - tracker/provider/task/runner
  - service state publish引数
  - shutdown task list

apps/scanner-core/src/prep_watchdeck/application/service_publisher.py
  - deep_backfill provider/field

apps/scanner-core/src/prep_watchdeck/domain/service_models.py
  - ServiceStateSnapshot.deep_backfill
  - 独立componentが使うDeepBackfillProgress型は残してよい

apps/web/src/lib/service-state.ts
  - deepBackfillの現行status選択

config/systemd/prep-watchdeck-service.service.in
  - --deep-backfill-*引数
```

`apps/scanner-core/src/prep_watchdeck/application/service_deep_backfill.py`をserviceからimportしない。
fileとpure testを削除せず、新しいCLIまたはsystemdへ再接続しない。

### 3.3 Focused verification

```bash
cd /home/tn/projects/prep-watchdeck/apps/scanner-core
uv run pytest -q \
  tests/test_service_deep_backfill.py \
  tests/test_service_runtime.py \
  tests/test_service_state.py
uv run ruff check src/prep_watchdeck/interfaces/cli.py \
  src/prep_watchdeck/application/service_publisher.py \
  src/prep_watchdeck/domain/service_models.py

cd ../web
bun test src/lib/service-state.test.ts
bun run check

cd ../..
bun test scripts/ops/install-user-services.test.mjs
rg -n -i 'deep[_-]?backfill|deepBackfill' \
  apps/scanner-core/src/prep_watchdeck/interfaces/cli.py \
  apps/scanner-core/src/prep_watchdeck/application/service_publisher.py \
  apps/scanner-core/src/prep_watchdeck/domain/service_models.py \
  apps/web/src/lib/service-state.ts \
  config/systemd/prep-watchdeck-service.service.in
git diff --check
```

最後の`rg`はexit 1が「参照なし」の正常結果になり得る。出力内容で判断し、command exitだけをtest失敗と
混同しない。

## 4. CP-02: Candidate consumerと74時間UIを先に切断

### 4.1 変更方針

- `DashboardRankingArea`、`DashboardRankingPanel`、`candidate-rule.ts`を削除する。
- `+page.svelte`からCandidate rankingを外す。
- `/api/rankings`、snapshot repositoryのCandidate ranking method、`rankings.ts`、Symbol Monitoring Railの
  Candidate順位表示を削除する。
- `DashboardMarketComparisonPanel`と`DashboardVpiExperimentPanel`はCandidateの子という意味を外し、
  Watchlistより前のcontext領域へ移す。値、判定、表示条件は変えない。
- `SelectedSymbolOverview`と`SymbolMarketContextCards`から74時間fieldだけを外す。
- Dashboard filter/raw sort/persisted settings/Symbol route/chart selectorから`74h`を削除する。
- 保存済み`74h`設定を受けた場合は既定の有効timeframeへfail-closed fallbackする。
- Candidateを広いランキングへ置換しない。

### 4.2 Target tests

```text
apps/web/src/lib/market/rankings.test.ts
apps/web/src/lib/market/candidate-rule.test.ts
apps/web/src/lib/market/chart-data.test.ts
apps/web/src/lib/market/dashboard-filters.test.ts
apps/web/src/lib/market/labels.test.ts
apps/web/src/lib/market/raw-sort.test.ts
apps/web/src/lib/server/snapshot-repository.test.ts
apps/web/src/lib/server/live-refresh.test.ts
apps/web/src/lib/server/dashboard-view-settings-repository.test.ts
apps/web/src/routes/api/dashboard-view-settings/dashboard-view-settings.test.ts
apps/web/tests/e2e/home.e2e.ts
apps/web/tests/e2e/monitoring-symbol.e2e.ts
apps/web/tests/e2e/responsive-layout.e2e.ts
apps/web/tests/e2e/smart-rank.e2e.ts
apps/web/tests/e2e/symbol-workspace.e2e.ts
```

### 4.3 Focused verification

```bash
cd /home/tn/projects/prep-watchdeck/apps/web
bun test \
  src/lib/market/rankings.test.ts \
  src/lib/market/chart-data.test.ts \
  src/lib/market/dashboard-filters.test.ts \
  src/lib/market/labels.test.ts \
  src/lib/market/raw-sort.test.ts \
  src/lib/server/snapshot-repository.test.ts \
  src/lib/server/live-refresh.test.ts \
  src/lib/server/dashboard-view-settings-repository.test.ts \
  src/routes/api/dashboard-view-settings/dashboard-view-settings.test.ts
bun run check
bun run build
bunx playwright test \
  tests/e2e/home.e2e.ts \
  tests/e2e/monitoring-symbol.e2e.ts \
  tests/e2e/responsive-layout.e2e.ts \
  tests/e2e/smart-rank.e2e.ts \
  tests/e2e/symbol-workspace.e2e.ts
```

1440pxと390pxで少なくとも次を確認する。

1. Candidate見出し・ranking・74時間ruleがない。
2. Market comparison/VPI、Watchlist、Selected detail、Smart Rankへ到達できる。
3. Bitget × Hyperliquid Core Perp比較が従来どおり表示される。
4. Symbol画面に旧Candidate順位が残っていない。
5. 保存済み74時間settingでblank pageまたは例外にならない。
6. 横overflowとkeyboard focus退行がない。

このcheckpointではbackend/schemaが旧74時間fieldとCandidate rankingをまだ生成していてよい。Webがそれを
表示・取得しない状態を先にgreenにし、producer削除後の型不整合を防ぐ。

## 5. CP-03: 74時間backend/public contractパージ

### 5.1 固定する最小契約

- scanner rowに74時間専用fieldがない。
- `summary.candidateRule74h`がない。
- `rankings.noTrade`は残る。
- Candidate用`rankings.timeframes`と`rankings.meta.timeframes`は出力しない。
- timeframeは`5m | 15m | 1h | 4h | 24h`だけである。
- OI 60分、activity phase、15m/1h/4h量倍率、Perp sidecarsは変わらない。
- schemaVersionは1、featureVersionは5、rulesetVersionは4とする。
- 新producerは74時間fieldを出力しないが、row/summary/rankingsの追加property許容により旧snapshotを
  readerが拒否しない。

### 5.2 削除対象

```text
apps/scanner-core/src/prep_watchdeck/domain/features/long_horizon.py
apps/scanner-core/src/prep_watchdeck/constants.py
apps/scanner-core/src/prep_watchdeck/models.py
apps/scanner-core/src/prep_watchdeck/config/filter_config.py
apps/scanner-core/src/prep_watchdeck/domain/dto.py
apps/scanner-core/src/prep_watchdeck/domain/screening/rankings.py
apps/scanner-core/src/prep_watchdeck/adapters/bitget_live/provider.py
apps/scanner-core/src/prep_watchdeck/adapters/fixture/provider.py
apps/scanner-core/src/prep_watchdeck/features/volume_ratio.py
apps/scanner-core/src/prep_watchdeck/screening/pipeline.py
config/scanner-filters/aggressive.toml
config/scanner-filters/balanced.toml
config/scanner-filters/conservative.toml
config/scanner-filters/README.md
fixtures/snapshots/basic.json
schemas/scanner-snapshot.schema.json
apps/web/src/lib/generated/scanner-snapshot.d.ts
```

`long_horizon.py`が他機能から未参照になったことを確認してから、`apply_patch`でfileを削除する。
generated TypeScriptは手編集せず、schema export後に生成する。

### 5.3 Focused verification

```bash
cd /home/tn/projects/prep-watchdeck/apps/scanner-core
uv run pytest -q \
  tests/test_domain_features.py \
  tests/test_config_and_models.py \
  tests/test_bitget_live_provider.py \
  tests/test_rankings_contract.py \
  tests/test_snapshot_contract.py \
  tests/test_service_snapshot.py
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run watchdeck export-schema --out ../../schemas/scanner-snapshot.schema.json

cd ../web
bun run generate:types
bun test
bun run check
bun run build

cd ../..
rg -n -i '74h|user_rule_74h|userRule74h|candidateRule74h' \
  apps/scanner-core/src apps/web/src config/scanner-filters schemas fixtures/snapshots/basic.json
git diff --check
```

最後の`rg`はproduction/config/schema/fixtureで参照0件を期待する。旧snapshot互換性testのlegacy fixture、
ADR、過去planは対象外としてpathを分けて確認する。

## 6. CP-04: scanner/gap auditとchart sourceのwindow分離

### 6.1 導出式

現行の最長短期量倍率は4時間で、5分足48本を使う。baselineは288 sampleである。

```text
required_5m_bars = baseline_sample_count + 2 * max_active_window - 1
                 = 288 + 2 * 48 - 1
                 = 383

required_1m_bars = required_5m_bars * 5
                 = 1,915
                 = 31時間55分
```

これはscanner判定とgap auditの必要量である。24時間価格・売買代金も288本なので383本以内に収まる。
一方、detail chartは入力windowを各timeframeへ集計して最大128本を表示する。入力を1,177本から383本へ
一律に減らすと、概算で次のように変わる。

| Timeframe | 1,177本入力 | 383本入力 |
|---|---:|---:|
| 1h | 約99〜100本 | 約32〜33本 |
| 4h | 約25〜26本 | 約8〜9本 |
| 24h | 約5〜6本 | 約2〜3本 |

したがって、scanner/gap auditとchart sourceに同じwindowを使わない。

```text
analysis/gap window: 383本5m = 1,915本1m = 31時間55分
chart source window: 1,177本5m = 5,885本1m = 98時間5分（暫定維持）
```

production codeでは二つの責務を明示的なhelper/fieldへ分離する。scanner row計算とgap auditには末尾383本
だけを渡し、chartは現行source深度を使う。gap auditのためにchart用98時間5分の1分足全件をPython
objectへ読み込まない。

### 6.2 検証

```bash
cd /home/tn/projects/prep-watchdeck/apps/scanner-core
uv run pytest -q \
  tests/test_config_and_models.py \
  tests/test_domain_features.py \
  tests/test_service_snapshot.py \
  tests/test_chart_artifacts.py \
  tests/test_gap_audit.py \
  tests/test_service_reconcile.py
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
```

fresh DBに自動deep seedを戻さない。coverage不足は`MISSING`として見えることを確認する。
scannerの31時間55分、chartの98時間5分warm-upが受け入れられない場合は、このCPへ常駐backfillを
足さずD-03を別計画にする。

## 7. CP-05: docsとfull local gate

実装後にだけ現行文書を更新する。計画時点で未来を`docs/current/`へ書かない。

更新候補:

```text
README.md
DESIGN.md
docs/README.md
docs/current/overview.md
docs/current/architecture.md
docs/current/data-contracts.md
docs/current/ui-workflow.md
docs/current/operations.md
docs/current/validation.md
docs/decisions/0010-retire-74h-candidate-deep-backfill.md
docs/decisions/0007-monitoring-only-product-boundary.md
docs/decisions/0008-candidate-oi-contract.md
docs/plans/active/p1-candidate-oi-contract/*
docs/plans/active/purge-74h-deep-backfill/*
```

新ADR 0010を追加する。ADR 0007/0008は削除せず、Candidate/74時間部分が0010でsupersededになった
事実と日付を追記する。ADR 0008のOI 60分部分は現行判断として残す。過去planの「当時実装された」
という履歴まで書き換えない。`DESIGN.md`のCandidate前提も実装後のinformation architectureへ同期する。

```bash
cd /home/tn/projects/prep-watchdeck
bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
npx -p @google/design.md designmd lint DESIGN.md
bash scripts/verify-local.sh
git diff --check
git status --short
git diff --stat
git diff --name-status
```

Windows viewの`scripts/verify-local.sh`差分は文書作成時点でmode-onlyだった。canonical Linuxで内容と
実行権限を再確認し、検証を弱める内容差分がないことを確認する。無関係な失敗は回帰と分離し、未解決の
ままPASSにしない。

## 8. CP-06: runtime qualification

restartは現行承認がある場合だけ行う。Repoのunit templateを変更しても、既に読み込まれたuser unitは
自動更新されない。現時点の実unitには旧`--deep-backfill-*`引数が残っているため、restartより前に
installerで意図した設定へ同期する。

### 8.1 unit driftの限定確認と反映

まず実在unit、現在の内容、state root、restart前状態を記録する。

```bash
cd /home/tn/projects/prep-watchdeck
repo_root="$(git rev-parse --show-toplevel)"
systemctl --user list-unit-files 'prep-watchdeck*'
systemctl --user cat prep-watchdeck-service.service
systemctl --user cat prep-watchdeck-web.service
systemctl --user show prep-watchdeck-service.service \
  -p MainPID -p ActiveState -p SubState -p NRestarts -p Environment
systemctl --user show prep-watchdeck-web.service \
  -p MainPID -p ActiveState -p SubState -p NRestarts -p Environment
```

`state_root`は上のservice unitの`PREP_WATCHDECK_STATE_DIR`と完全一致する絶対pathを使う。推測したpathや
別のstate rootへ置き換えない。次の順序を変えない。

```bash
state_root='<systemctl showで確認した絶対path>'

# 旧deep引数が残る現状ではexit 1を期待する。exit 0なら実unitが既に同期済みかを再確認する。
bash scripts/ops/install-user-services.sh --check \
  --repo-root "$repo_root" --state-root "$state_root"

# checkが非0だった場合だけ差分を表示する。
bash scripts/ops/install-user-services.sh --dry-run \
  --repo-root "$repo_root" --state-root "$state_root"
```

許容するdriftは、service `ExecStart`から旧`--deep-backfill-*`引数を除く今回の意図した差分だけである。
WorkingDirectory、Environment、state root、UV path、Web unit、restart policy、timeoutなど別の差分があれば
`--apply`せず停止する。差分が限定されている場合だけ反映し、表示されたbackup pathを記録する。

```bash
bash scripts/ops/install-user-services.sh --apply \
  --repo-root "$repo_root" --state-root "$state_root"
bash scripts/ops/install-user-services.sh --check \
  --repo-root "$repo_root" --state-root "$state_root"
systemctl --user cat prep-watchdeck-service.service
systemctl --user cat prep-watchdeck-web.service
```

`--apply`はdaemon-reloadとenableだけを行い、serviceをrestartしない。2回目の`--check`がexit 0で、実unitから
旧deep引数が消えたことを確認してから、scannerとWebを各1回だけrestartする。同じunitを繰り返しrestart
しない。

```bash
systemctl --user restart prep-watchdeck-service.service
systemctl --user restart prep-watchdeck-web.service
```

### 8.2 restart後の確認

restart後は次を記録する。

- scanner/WebのMainPID、ActiveState、SubState、NRestarts
- DuckDB writer process数
- 3回連続snapshotの`runId`、`generatedAt`、row数、status
- `summary.perpVenueComparison`のitem/source statusと鮮度
- reconcile状態、OI reference状態、Web health
- scanner CPU%、RSS、snapshot間隔、chart file数
- 1440px/390pxの実画面結果

成功条件:

- 3回連続でsnapshotが進む。
- Bitget rowsとPerp比較が継続する。
- serviceがrestart loopせず、DuckDB writerが1 processである。
- Candidate/74時間UIがなく、Watchlist/Selected detail/Perp比較が使用できる。

即時停止・回復条件:

| Failure | Action |
|---|---|
| unit driftが旧deep引数除去以外を含む | `--apply`せず、実unit・rendered unit・差分を保存して停止する |
| `--apply`後の`--check`が失敗 | restartせず、installerが表示したbackupを保持して停止する |
| snapshot更新停止 | logとMainPIDを保存し、追加変更を止める |
| 複数DuckDB writer | 追加起動を止める。DBへ新しいwriterを接続しない |
| Bitget scanまたはPerp比較退行 | checkpoint commitを逆順にrevertする |
| restart loop | 同じunitを繰り返しrestartせず原因を記録する |
| schema/DB migrationが必要 | scope超過として停止し、別計画へ切り替える |

## 9. Commit・公開境界

local commitを許可されている場合は、rollback可能なcheckpoint単位に分ける。

```text
CP-01: Disconnect production deep backfill
CP-02: Remove 74h Candidate consumers
CP-03: Purge 74h scanner contract
CP-04: Separate scanner and chart history windows
CP-05: Synchronize current documentation
```

各commit前に`git diff --cached --name-status`で対象を確認する。無関係な既存script差分とzipをstageしない。
push、PR、merge、service restartは本runbookだけを根拠に実行しない。

## 10. 完了報告に必ず含めるもの

- PASS / PARTIAL / BLOCKED
- 実装したCPと未実施CP
- ACごとのstatusと再現可能なevidence
- 最終branch、HEAD、worktree状態
- 実行testとexit code
- runtimeを実行したか、していないか
- DB writer、snapshot 3回、Perp比較、Web画面の結果
- CPU/RSS/snapshot間隔の変更前後値。取得不能項目は未確認と明記
- chart、snapshot、short candle、reconcileが残っていること
- fresh stateでscannerは最大31時間55分、現行chart深度は最大98時間5分warm-upする残risk
