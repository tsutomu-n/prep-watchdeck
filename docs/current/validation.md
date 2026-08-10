# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-09T20:30:00+09:00`
- 検証: `2026-08-09T20:30:00+09:00`
- 文書更新作業: `2026-08-09_20:30`（Asia/Tokyo）
- 状態: `現行`

---

## Full local gate

Repo全体の標準gate:

```bash
bash scripts/verify-local.sh
```

scriptが実行する順序:

1. maintenance tests
2. document metadata checker
3. document local-link checker
4. scanner-core pytest
5. Ruff check / format check
6. Pyrefly
7. Web unit tests
8. Svelte check
9. production build
10. Playwright E2E

E2E、performance、soakのstateは`PREP_WATCHDECK_STATE_DIR`配下の`tmp/<gate>/runtime`へ
隔離する。現役serviceが同じDuckDBを使用中なら、full gateへ別の一時state rootを指定する。

## 変更範囲ごとの最小gate

### 文書

```bash
bun test scripts/maintenance/document-metadata.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun test scripts/maintenance/document-links.test.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
```

metadata/link checkerは形式とlocal linkの存在を確認する。内容がcodeと一致するかは、
対象のCLI help、route、schema、config、testも別に照合する。

### Scanner-core

```bash
cd apps/scanner-core
uv run python -m pytest -q <関連test>
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
```

広いscanner変更では`<関連test>`だけで終えず、全pytestを実行する。

VPI-Lite+のCoreとCold snapshot統合では、少なくとも次も実行する。

```bash
cd apps/scanner-core
uv run python -m pytest -q \
  tests/test_vpi_ewma.py \
  tests/test_vpi_compute.py \
  tests/test_vpi_classify.py \
  tests/test_vpi_config.py \
  tests/test_vpi_service_integration.py \
  tests/test_service_snapshot.py \
  tests/test_settings.py
```

closed 1分足だけの使用、open candle非影響、disabled/通常scan非影響、benchmark summary、
row display複製、symbol単位failure isolation、既存ranking・row判定不変を確認する。

### Web / UI

```bash
cd apps/web
bun test
bun run check
bun run build
```

interaction、route、responsive layoutを変えた場合は関連Playwright E2Eも実行する。
releaseまたは複数surfaceへ及ぶ変更はrootのfull local gateで閉じる。

VPI-Lite+ UIでは、局所parserの全enum/範囲/不正payload、概要panelのscore非表示、選択銘柄だけの
補助詳細、自動売買シグナルではない旨、既存row・ranking非影響、Hot ticker deltaでCold VPIが変わらない
ことをunitとPlaywrightで確認する。`1440x900`、`1280x800`、`390x844`でBefore/Afterを比較し、
横overflow、主要操作の欠落、誤推奨表現がないことも確認する。

## Service resilience gate

REST retry、watchdog、service supervisionのfocused gate:

```bash
cd apps/scanner-core
CI=true timeout 90 uv run python -m pytest -q \
  tests/test_bitget_client.py \
  tests/test_service_watchdog.py \
  tests/test_service_runtime.py
```

確認対象:

- retry対象、上限、`Retry-After`、backoff、timeout、cancellation
- 非retryable 4xx、invalid JSON、Bitget business errorの即時失敗
- timestamp前進、startup grace、停止後の復帰、外部障害との分離
- watchdog failure、通常終了、Ctrl-C、無効化時のtask cleanup
- state、snapshot、ticker、backfill、reconcile、deep-backfill taskのcancel/await
- CLI既定値と限定されたREST probe

mock gateはlive Bitget障害やlive process killを発生させず、現役stateへwriterを接続しない。

## Runtime切替後の確認

runtime変更を実serviceへ反映した場合はtest greenと分けて確認する。

```bash
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"
state_root="$(realpath -m "${PREP_WATCHDECK_STATE_DIR:-var}")"

systemctl --user show prep-watchdeck-service.service \
  -p ActiveState -p SubState -p MainPID -p NRestarts -p Restart -p RestartUSec

jq '{generatedAtMs,dataAsOfMs,diagnostics,backfill,reconcile}' \
  "$state_root/snapshots/service-state.json"

curl --fail http://127.0.0.1:5173/api/health
lsof "$state_root/watchdeck.duckdb"
```

確認するのは、想定したprocessへの切替、`active/running`、process manager policy、
state/data timestamp前進、Web health、単一DuckDB writer、Past Note、Dashboard settings維持である。
固定PIDや固定row数は合格条件にしない。Bitget障害中に再起動を繰り返さない。

## Realtime gate

```bash
cd apps/web
bun run test:performance
SOAK_DURATION_MS=3600000 bun run test:soak
```

performanceはtransport、Hot apply、Raw Sort、Long Task、Cold snapshot反映、hidden中pollを確認する。
継続的なHot更新は50ms超Long Task 0件、apply p95 8ms以下を必須とする。Raw Sortは最初の
`1h`/`15m`切替を各100ms以下、その後20回のsteady-state p95を50ms以下とする。

Cold snapshotは50ms超Long Taskの件数と全durationを診断証拠へ残すが、件数だけでは失敗にしない。
snapshot fetch完了からfreshness DOM反映までを計測windowとし、最大Long Task 100ms以下、反映
200ms以下を必須とする。これにより51msと重大なmain-thread停止を区別しつつ、上限超過は
fail-closedに扱う。固定waitや反映後の処理はCold計測windowへ含めない。

soakはrequest failure、row維持、chart同時数、hidden中poll、stale検出と回復、heap傾向、
symbol遷移を確認する。
soakの各sampleはrequest完了を最大5秒だけ待ち、最終`inFlight=0`を必須とする。時間内に
drainしない場合は失敗であり、待機をrequest failureやhung requestの免除に使わない。
過去baselineは現行合格を保証しないため、比較時は同じcommit、fixture、row数、環境を記録する。

## State / Archive gate

```bash
bun test \
  scripts/maintenance/retired-records-archive.test.mjs \
  scripts/maintenance/state-dir.test.mjs \
  scripts/ops/watchdeck-daily-summary.test.mjs
```

state移行またはRepo history最終化を行う場合は、scriptのdry-runと専用checkerを先に使う。

- scanner-coreとWebが同じ絶対state rootを解決する。
- layout v2 targetをDB/WAL、snapshot、Past Note、Dashboard settings、usage events、opsへ限定する。
- source全体とArchiveのfile list・SHA-256、v2 common files、監視annotation件数を照合する。
- markerless layout v1 Archiveを検証でき、未知versionを拒否する。
- snapshot `runId`とchart `snapshotRunId`を照合する。
- old/new stateが同時に更新されない。
- Archive後のsource、tracked集合、Archive本体のdriftを拒否する。
- delete/apply前にrollback sourceとArchive証拠が残る。

## Monitoring-only boundary gate

```bash
bun test scripts/maintenance/monitoring-only-boundary.test.mjs
cd apps/web
bun run test:e2e -- tests/e2e/retired-routes.e2e.ts
```

production sourceに退役domain、record path、route fileが残らず、旧APIが全methodで404となること、
Past Note routeが引き続き存在することを確認する。scanner内部の`NO_TRADE`と、Archive・test・v1互換
readerに必要な旧identifierだけを明示的allowlistとする。

## 証拠の残し方

検証記録には次を残す。

- 東京時間`yyyy-mm-dd_hh:mm`
- branch、HEAD、既存差分
- 実行commandと結果
- 使用した隔離state root
- 未実行項目と理由
- runtime切替の有無
- 残リスクとrollback

現行文書へ一回限りのPID、件数、移行ログを累積しない。再開に必要な短期状態はrepo rootの
`HANDOFF.md`、完了計画と長期証拠はRepo外Archiveへ置く。`.ai_memory/HANDOFF.md`など
root以外の旧handoffを再開正本にしない。

## 完了判定

test greenだけでは完了にしない。変更内容に応じてcode、schema、CLI help、current docs、
runtime path、monitoring state、performance/soak、未実行項目を監査する。実行できない必須gate、
sourceとの不一致、単一writer違反、未照合の削除対象がある場合は未完了とする。

## Candidate / OI focused verification

74h三値AND、Candidate-only gate、noTrade診断、OI out-of-order upsert、exact lookback、
24時間retention、restart再利用、cycle劣化、UNKNOWN無加点、WS ticker/candle再取得は
scanner-core focused testsで確認する。exact 60分、retention、restartはseed済み一時DuckDBの
deterministic integration testを正本とし、finite live smokeの経過時間では代用しない。

Web focused verificationは有効summaryと不正summary fallback、Candidate空状態、OI四状態、
74h三状態、VPI-Lite+ availability維持を含む。最終判定はfocused test後に
`bash scripts/verify-local.sh`を実行する。
