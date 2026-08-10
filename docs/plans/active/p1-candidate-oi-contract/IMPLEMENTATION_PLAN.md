# P1 Candidate / OI 契約修正 実装計画

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-10T11:59:58+09:00`
- 検証: `2026-08-10T11:59:58+09:00`
- 状態: `実装計画`

---


## 0. メタデータ

- Plan ID: `PLAN-P1-CANDIDATE-OI-001`
- Revision: `6`
- Target repo: `tsutomu-n/prep-watchdeck`
- Baseline commit: `8c3ecd4bf9ea16db0e99a0000f2f37fd89c3f583`
- Canonical path:
  - `docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.md`
  - `docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.ai.json`
- Current status: `complete`

## 1. 目的とCurrent plan goal

### Objective

Personaレビューで確認した候補選定とOIの意味不整合を解消し、設定・計算・ランキング・UI・文書を一致させる。

### Current plan goal

現行の監視専用境界を維持したまま、以下を一つのbounded waveとして完成させる。

1. 74h価格条件と24h USDT売買代金増加条件を個別の三値で評価し、両方が`True`の場合だけ複合値を`True`とする。
2. Candidateの4ランキングだけを複合値`True`でgateし、Watchlist / Raw Sort / Smart Rank / noTrade診断の広い監視面を維持する。
3. OIを既存single-writer DuckDBへ5分bucket・24時間retentionでadditiveに保存し、exact 60分前bucketとの比較から状態を算出する。
4. 欠損・stale・invalid OIを`UNKNOWN`とし、注目度へ正加点しない。
5. Candidate ruleと選択銘柄のOI状態を最小UIで説明し、feature/ruleset version、tests、current docs、ADR、living plansを同期する。
6. Phase Bの初期runtime qualificationを通し、テスト内だけの完成を防ぐ。

### 完成境界

- **Phase A**: `AC-P1-*`全PASS → P1修正wave完成。
- **Phase B**: `AC-RQ-*`全PASS → 監視専用v1.0のコード完成候補・初期runtime適格。
- 自然な24時間WebSocket切断は非blocking運用観測。未観測ならresidual riskへ明記する。

### Concrete deliverables

1. 74h三値ANDとcomponent reason codes
2. Candidate-only ranking gate
3. `summary.candidateRule74h` metadata
4. bounded OI sample store/API
5. service snapshotへのexact 60m OI配線
6. `UNKNOWN`無加点
7. Candidate helpとSymbol Monitoring Rail OI表示
8. feature/ruleset version更新
9. 最小focused testsとfull gate
10. current docs/ADR/living plans
11. 初期runtime qualification証拠

## 2. Scope

### Scope in

- `domain/features/long_horizon.py`の三値意味論
- Candidate ranking eligibility
- 74h reason codes / summary metadata
- 既存DuckDB service storeへのOI sample table/API
- `service_snapshot.py`のOI sampling/lookup配線
- OI classification/scoring semantics
- Candidate説明とSymbol Monitoring Railの最小表示
- version/tests/docs/runtime qualification

### Scope out

- VPI-Lite+、Smart Rank algorithm、Watchlist列、UI全面刷新
- Alert/通知/Symbol検索/Focus Queue
- Spread/Liquidation/Order Book/Funding percentile/Market Cap API
- Private API/注文/実約定/損益/Copy/Grid/Bot
- 新規OSS、DB/framework置換、default symbol数変更
- performance閾値緩和、目的外refactor

## 3. 事実・推論・仮定・Unknown

### Facts

- Baselineの74h compositeは`price_match or volume_match`。
- DTOには長期指標と`userRule74hMatched`が既にある。
- Candidateランキングは`changeUp/changeDown/turnoverTop/volumeUp`で、74h compositeをgateにしていない。
- configに`change_lookback_minutes = 60`がある。
- `build_scanner_rows()`は`previous_oi_by_symbol`を受け取れる。
- 標準service snapshotはprevious OIを渡していない。
- `ticker_latest`は最新値であり、単独では60分前を復元できない。

### Inferences

- Candidateだけをgateすれば、主条件と広い監視面を両立できる。
- 5分bucket×24時間で60分比較に十分かつboundedにできる。
- Web DOM/Hot pollingを変えないため、通常はWeb 1時間soak再実行よりscanner/store focused testsが重要。

### Assumptions

- 本waveの「出来高」は現行実装どおりUSDT quote turnoverを意味する。
- Candidateは主条件合致者、Watchlistは広い監視Universeである。
- `holdingAmount`は現行Public tickerのOI sourceとして維持されている。

### CP-001で解決した事項

- 現HEADは専用branch上の`8c3ecd4`、開始時worktreeはclean。
- concrete storeは`adapters/duckdb/service_store.py`で、既存OI history tableはない。
- snapshot ranking builderへ既存exportと同じ`rankings.noTrade`診断を接続し、全rowsの`NO_TRADE`から維持する。
- ticker freshnessは既存service snapshotの2分上限をcurrent OIにも再利用する。
- reconnect testはticker回復を証明するが、ticker/candle両方の再購読・回復証拠をfocused testで補う。
- `.codex/SP_STATE.md`は以前のwave用であり、今回の正本は本living plan二点と現行Repoである。
- 完了時もユーザー要求に従って両living planを追跡・同期したまま残す。

## 4. 選択肢と決定

- **A 現状維持**: 不採用。意味不整合を残す。
- **B 74h ANDだけ修正、OIをscoreから外す**: 縮退案。既存意図を捨てるため不採用。
- **C 74h AND + Candidate gate + local OI history**: 採用。Public/local-first/single-writerを維持し、既知P1だけを閉じる。
- **D 外部OI history backfill**: 不採用。追加API/rate-limit/定義負債が大きい。

## 5. Acceptance criteria

| ID | 必須 | 条件 | 検証 |
|---|---:|---|---|
| AC-P1-001 | Yes | 74h componentを三値で保持し、両方Trueだけ複合True | parameterized unit test |
| AC-P1-002 | Yes | 片方達成、履歴不足、zero baselineを複合Trueにしない | unit test |
| AC-P1-003 | Yes | 価格/売買代金の達成reasonを独立追加 | DTO/provider test |
| AC-P1-004 | Yes | Candidateだけ複合True。Watchlist/noTrade診断を保持 | ranking + E2E |
| AC-P1-005 | Yes | OIを5分bucketでidempotent upsertし24h超をprune | store test |
| AC-P1-006 | Yes | exact 60分前bucketだけ比較、欠損はUNKNOWN | resolver + snapshot test |
| AC-P1-007 | Yes | UNKNOWN OIへ正加点しない | priority test |
| AC-P1-008 | Yes | active Candidate条件と選択銘柄OIを最小表示。Watchlist列なし | focused E2E |
| AC-P1-009 | Yes | feature/ruleset versionを3へ、schemaVersion維持 | snapshot test |
| AC-P1-010 | Yes | DB変更はadditive、rollbackにDROP不要 | migration/store test |
| AC-P1-011 | Yes | 既存監視挙動がfull gateを通る | `bash scripts/verify-local.sh` |
| AC-P1-012 | Yes | current docs/ADR/living plansが最終実装・証拠と一致 | doc/plan validation |
| AC-P1-013 | Yes | stale/invalid current OIをsample/比較せずUNKNOWN | service snapshot test |
| AC-RQ-001 | Yes | fixture one-command startupで主要画面と新意味論を確認 | runtime smoke |
| AC-RQ-002 | Yes | 隔離stateのfinite live smokeが本番stateを変更せず成功 | CLI/doctor evidence |
| AC-RQ-003 | Yes | runtimeでvalid OI sample保存、同bucket重複なし | DB query/evidence |
| AC-RQ-004 | Yes | restart後もadditive table/既存stateを再利用 | controlled restart |
| AC-RQ-005 | Yes | reconnect→再購読→ticker/candle ingest回復をfocused testで証明 | reconnect test |
| AC-RQ-006 | Yes | artifact上でCandidate/Watchlist/Noneの責務分離を確認 | fixture/live assertion |
| AC-RQ-007 | Yes | final full gate/diff audit、未解決P0/P1なし | commands + audit |

## 6. Numbered checkpoints

### CP-001 Baseline・Repo契約・living plan同期

**Goal:** 現HEAD、指示、store、tests、templatesを確定し、計画を現実へ合わせる。

**Work:** `git status/diff/HEAD`、全`AGENTS.md`、README/DESIGN/current docs/ADR、plan template/schema、対象source/testsを確認。専用branchを作成。現HEADが異なる場合はresetせずbaseline/facts/target filesを更新。

**Target:** 本plan、AI plan、Repo instructions。

**AC:** AC-P1-012

**Stop:** 既存未コミット変更と衝突、製品境界の明示変更、同Goalの既存planと競合。

### CP-002 Focused redを最小追加

**Goal:** 変更契約だけをテストで固定する。

**Work:** 74h truth table、Candidate gate、OI exact 60m/missing/stale/retention、UNKNOWN無加点、最小UI test。既存testで十分なら再利用。

**AC:** AC-P1-001〜010, AC-P1-013

**Completion:** 意図した現行不整合でred。無関係failureではない。

### CP-003 74h三値AND・reason codes

**Target:** `domain/features/long_horizon.py`、provider/DTO変換、関連tests。

**Work:** component bool|nullを導入。history不足/zero baselineをNone。複合はcomponentのどちらかNoneならNone、それ以外AND。達成componentだけreason code追加。

**AC:** AC-P1-001〜003

### CP-004 Candidate-only gate・summary metadata

**Target:** rankings builder、provider、Candidate consumer/tests。

**Work:** 全rowとCandidate sourceを分離。Candidate sourceは`userRule74hMatched is True`かつ既存除外条件。snapshot rows/Watchlist/Raw Sort/Smart Rank/noTrade診断は維持。active configからsummary metadataを出す。

**AC:** AC-P1-004, AC-P1-008

**Failure:** snapshot全rowをfilter、Smart Rankまでgate、閾値hardcode。

### CP-005 Additive OI store

**Target:** concrete DuckDB service store、service models、store tests。

**Contract:** `open_interest_samples(symbol,bucket_ts_ms,holding_amount,source_ts_ms,updated_at_ms)`、PK `(symbol,bucket_ts_ms)`、5分bucket、24h retention。

**Work:** 既存lock/transaction/single writerを再利用し、bulk upsert + exact target load + pruneをboundedに行う。N+1 query禁止。既存信頼可能historyがあれば再利用しdecision logへ記録。

**AC:** AC-P1-005, AC-P1-010, AC-P1-013

### CP-006 Service snapshotへOI 60m配線

**Target:** `application/service_snapshot.py`、OI feature、priority、store tests。

**Work:** valid/fresh current tickerだけsample。source timestampでbucket化。lookback configからexact target keyを一括生成/load。previous mapを`build_scanner_rows()`へ渡す。missing/staleはUNKNOWN。UNKNOWN fallback score=0。

**AC:** AC-P1-006, AC-P1-007, AC-P1-013

### CP-007 最小UI・version

**Target:** Candidate component、Symbol Monitoring Rail、labels/help、provider versions、focused E2E。

**Work:** summary metadataを局所validationしactive閾値を表示。不正時はgeneric fallback。Monitoring Railへ`OI 60分`を1項目追加。強気/弱気へ翻訳しない。Watchlist列なし。feature/ruleset=3。

**AC:** AC-P1-008, AC-P1-009

### CP-008 Focused green・文書・full gate

**Work:** focused green、README/current docs/ADR/両plan更新、`bash scripts/verify-local.sh`を1回、diff/secret/runtime artifact監査。

**AC:** AC-P1-009〜013

### CP-009 One-command/finite live qualification

**Work:** `RUNTIME_QUALIFICATION.md`のRQ-01/RQ-02。fixture startと隔離live smoke。実URL、state path、exit codeを記録。

**AC:** AC-RQ-001, AC-RQ-002

### CP-010 OI runtime/restart qualification

**Work:** valid OI sampleのruntime保存、同bucket idempotency、controlled restart、同state再利用。exact 60mはdeterministic testで証明し、実時間60分待機を必須にしない。

**AC:** AC-RQ-003, AC-RQ-004

### CP-011 Reconnect・artifact semantics

**Work:** 既存reconnect testを実行。不足時だけfocused test追加。Candidate/Watchlist/None責務をartifactで確認。

**AC:** AC-RQ-005, AC-RQ-006

### CP-012 Final audit

**Work:** full gate再確認（CP-008後にsource変更がなければ同証拠再利用可）、complete diff、両plan同期、final result/goal gap/residual risk記録。

**AC:** AC-RQ-007、全mandatory AC

## 7. Minimal TDD policy

```text
既存test探索
→ 必要最小のfocused red
→ 最小実装
→ focused green
→ full gate 1回
```

新test framework、qualification framework、新OSSは追加しない。WebのHot polling/DOM/chart lifecycleを変更しない限りperformance/1h soakは必須にしない。該当経路を変更した場合のみ既存commandを実行する。

## 8. Critical risks

1. OR→ANDだけ直してCandidateへ接続しない。
2. Candidate gateを全rowへ誤適用する。
3. `None`を`False`へ黙って丸める。
4. latest/nearest OIを60分前と偽る。
5. stale current OIをfresh sampleとして保存する。
6. OI履歴を無期限保存、N+1 query、別writer追加。
7. UNKNOWNへ正加点。
8. Candidateが履歴不足で空なのに障害/偽dataで埋める。
9. UI追加を口実に情報密度を膨張。
10. Persona preferenceへscope creep。

## 9. Stop conditions

- 現Repoで対象契約が消失・大幅変更している。
- `holdingAmount`の意味が不明またはsource変更。
- 既存信頼可能OI historyと重複する。
- Candidate gateが最新の明示製品契約と衝突する。
- baseline failureと今回regressionを切り分けられない。
- 外部write、secret、不可逆操作が必要。

停止時は該当AC/CP、証拠、影響、safe repo state、最小再開条件を両planへ記録する。

## 10. Progress / Final result

実装中は各Checkpoint後に、command、working directory、exit code、HEAD、要約、evidenceを両planへ追記する。

```text
Plan goal:
Actual result:
Mandatory AC passed:
Failed / blocked AC:
Changed files:
Commands and exit codes:
Runtime qualification:
Residual risks:
Goal gap:
Remaining work:
```

### CP-001 evidence

- Status: `passed`; next: `CP-002`.
- Branch/HEAD: `ai/p1-candidate-oi-20260809-1818` / `8c3ecd4bf9ea16db0e99a0000f2f37fd89c3f583`.
- `git status --short`: exit 0, no output.
- `git diff --stat`: exit 0, no output.
- Focused scanner baseline: CWD `apps/scanner-core`, HEAD `8c3ecd4bf9ea16db0e99a0000f2f37fd89c3f583`, exit 0, `58 passed in 4.31s`.

## 11. 条件付き承認で固定した実装契約

1. 74h gateは`rankings.timeframes`のCandidate 4ランキングだけへ適用する。`rankings.noTrade`は全rowsの`NO_TRADE`診断から構築して維持する。
2. price/turnover componentは`bool | None`。どちらかが`None`ならcompositeも`None`。zero/nonfinite priceまたはturnover baselineは`None`であり`False`へ丸めない。
3. `summary.candidateRule74h`はactive ruleに加え、非`NO_TRADE`のCandidate universe基準で`eligible`、`notMatched`、`unknown`件数を出す。履歴不足でCandidateが空でも正常なsnapshotとする。
4. OI bucketはBitget `source_ts_ms`を5分単位でfloorする。
5. 同一symbol/bucketのupsertはincoming `source_ts_ms`が既存値より新しい場合だけ更新する。同値・古いout-of-order payloadは既存sampleを保持する。
6. `change_lookback_minutes`は正数かつ5の倍数というbucket境界を満たし、現在の表示・分類契約と同じ`60`だけを設定load時に許容する。
7. DuckDB DDL/init失敗はservice startupを失敗させる。個別snapshot cycleのOI upsert/load/prune失敗は全銘柄OIを`UNKNOWN`、加点0とし、`summary.oiDiagnostics`へ明示してsnapshot発行を継続する。
8. UI文言はOI `UNKNOWN`を「不明」、74h `None`を「判定不能」とする。
9. VPI-Lite+のOI availability表示は変更・削除しない。重複整理は非VPIかつ完全同義と確認できた表示だけに限定する。
10. finite live smokeは接続・保存の初期確認だけに使う。exact 60m、retention、restart再利用はseed済み一時DuckDBのdeterministic integration testで証明する。
11. baseline evidenceは次の再現結果だけを採用する。

    ```text
    cwd=/home/tn/projects/prep-watchdeck/apps/scanner-core
    HEAD=8c3ecd4bf9ea16db0e99a0000f2f37fd89c3f583
    command=uv run python -m pytest -q tests/test_domain_features.py tests/test_rankings_contract.py tests/test_bitget_live_provider.py tests/test_service_snapshot.py tests/test_service_runtime.py tests/test_ws_shards.py tests/test_vpi_service_integration.py
    exit_code=0
    result=58 passed in 4.31s
    ```

12. durable decisionは既存ADR 0007を変更せず、新規ADR 0008へ記録する。
13. basic fixtureはactive balanced rule（price 4.0%、turnover 15.0%）と非`NO_TRADE` artifact値を照合し、eligible 1、notMatched 0、unknown 3、eligible symbol `ALTUSDT`を確認済み。実装後のFixtureProvider出力testが同じ結果を示した場合だけE2E期待値`1/1`を採用する。

### Failure semantics

- DDL/init failure: fail closed at service startup.
- Cycle OI failure: publish the snapshot with every OI state `UNKNOWN`, zero OI score contribution, and an explicit diagnostic; do not publish partial per-symbol OI states.
- Candidate history warmup: empty Candidate is a valid non-error state; Watchlist and all snapshot rows remain available.

## 12. 実装・検証結果（Revision 5）

### Checkpoint evidence

- CP-002: 74h/Candidate最小REDは`9 failed, 11 passed`、OI store/model最小REDはimport errorでexit 4、UI label最小REDは未実装exportでexit 1。いずれも狙った契約不在を確認した。
- CP-003〜CP-004: 74h三値AND、component reason、Candidate-only gate、全rows由来`rankings.noTrade`、version/summaryを実装。focused GREENは`20 passed in 0.31s`。
- CP-005〜CP-006: additive OI table、newer-source-only upsert、24h retention、exact lookback、config validation、cycle degraded diagnostic、UNKNOWN無加点を実装。store/snapshot focused GREENは`22 passed in 1.12s`。
- CP-007: Candidate rule validation/fallback、OI/74h日本語label、Monitoring Rail、非VPI重複表示整理を実装。Svelte check 0 errors/warnings、focused E2E `23 passed in 17.4s`。
- CP-008: README/current docsと新規ADR 0008を同期。scanner対象総合focusedは`85 passed in 4.69s`、Ruff lint/formatとpyreflyはPASS。
- CP-009: `/tmp/prep-watchdeck-p1-rq1-final.iS3nMM`でfixture one-command起動。wrapper exit 0、health/home/symbol/Candidate/Watchlist/Smart Rank/74h/OI表示、sentinel hash不変、controlled SIGINT後listenerなしを確認。
- CP-010: `/tmp/prep-watchdeck-p1-live.SrKFei`でpublic Bitget finite serviceを実行。service/publish/doctor wrapper exit 0、schema ready、OI sample 1480、2 buckets、duplicate 0、invalid 0、sentinel hash不変を確認。exact 60m/retention/restartはseed済み一時DuckDB testで決定論的にPASS。
- CP-011: reconnect testは同一ticker/candle specを2回sourceへ渡し、再接続後にticker 1件とcandle 1件を永続化。fixture artifactはCandidate `ALTUSDT`のみ、Watchlist 5 rows、noTrade `THINUSDT`、履歴不足rows保持。
- CP-012: 初回full gateはresponsive test専用fixtureがCandidate 1件化を考慮せず1件失敗。test専用に長短2候補をseedしてfocused PASS後、full gateを再実行しexit 0。

### Final commands

```text
cwd=/home/tn/projects/prep-watchdeck/apps/scanner-core
command=uv run python -m pytest -q tests/test_domain_features.py tests/test_rankings_contract.py tests/test_bitget_live_provider.py tests/test_snapshot_contract.py tests/test_config_and_models.py tests/test_service_snapshot.py tests/test_service_runtime.py tests/test_ws_shards.py tests/test_vpi_service_integration.py
exit_code=0
result=85 passed in 4.69s

cwd=/home/tn/projects/prep-watchdeck/apps/web
command=bun run test:e2e tests/e2e/home.e2e.ts tests/e2e/monitoring-symbol.e2e.ts
exit_code=0
result=23 passed in 17.4s

cwd=/home/tn/projects/prep-watchdeck
command=bash scripts/verify-local.sh
exit_code=0
result=maintenance 81; scanner pytest 225; web unit 174; Playwright 56; Ruff lint/format, pyrefly, Svelte check, build PASS

cwd=/home/tn/projects/prep-watchdeck
command=git diff --check
exit_code=0
result=no whitespace errors
```

### Acceptance result

| AC | 結果 | 主証拠 |
|---|---|---|
| AC-P1-001〜003 | PASS | 74h truth table/component/reason tests、focused 85、full scanner 225 |
| AC-P1-004 | PASS | Candidate gate/noTrade unit、fixture artifact、Web E2E |
| AC-P1-005〜007 | PASS | OI store/exact lookup/retention/restart/score tests |
| AC-P1-008〜010 | PASS | Web E2E、version/schema test、additive migration test |
| AC-P1-011 | PASS | `bash scripts/verify-local.sh` exit 0 |
| AC-P1-012 | PASS | ADR 0008、current docs、両living plan、metadata/link/JSON checks |
| AC-P1-013 | PASS | stale/invalid/current OI snapshot tests |
| AC-RQ-001 | PASS | isolated fixture runtime wrapper exit 0 |
| AC-RQ-002〜004 | PASS | isolated public live wrapper exit 0、DuckDB audit、deterministic restart test |
| AC-RQ-005 | PASS | ticker/candle reconnect focused test |
| AC-RQ-006 | PASS | fixture artifact responsibility assertion |
| AC-RQ-007 | PASS | final full gate/diff/scope audit |

### Final result

- Status: `PASS`。
- Branch/HEAD: `ai/p1-candidate-oi-20260809-1818` / 本planを含む最終local commit（`git rev-parse HEAD`で解決）。
- Commit state: 監査済みの今回差分だけを選択的にstageし、本planを含む最終local commitとして保存する。
- Mandatory AC: `20 PASS / 0 FAIL`。
- Scope外変更: `0`。依存追加、private API、Watchlist列、Raw Sort、Smart Rank algorithm、取引機能変更なし。
- 未解決P0/P1: `0`。
- Goal gap / remaining work: `none / 0`。
- Residual risk: 自然な24時間WebSocket切断は同期gateで未観測。決定論的reconnect testをPASSし、
  運用観測だけを非blockingで残す。2026-08-10のcontrolled restartではservice停止が30秒以内に
  完了せずsystemdがSIGKILLへ移行したが、再起動後の状態・data・single writerに破損はない。

## 13. PR review remediation（Revision 6）

- 旧v2/cached snapshotは`candidateRule74h` metadataを持たず、ランキングが現行74h gate済みとは
  証明できないため、fallbackを「条件詳細を取得できない／snapshot更新後に再確認」へ変更した。
- UI・分類・retentionがすべてOI 60分を公開契約としているため、設定値を`Literal[60]`へ固定した。
  将来可変化する場合は状態名、UI、retention、testsを同時に更新する。
- 最小REDはWeb `1 failed, 1 passed`、scanner `2 failed, 10 passed`。実装後の同一focused
  GREENはWeb `2 passed`、scanner `12 passed`。
- このremediationはCandidate/OI契約の不整合除去だけで、Watchlist、Raw Sort、Smart Rank、
  VPI-Lite+、schemaVersion、依存関係を変更しない。
- 最初のpost-review full gateは、JSON追記位置と不正値testの型検査経路を検出してexit 1。
  JSON構文を修正し、runtime validation testを`model_validate`へ変更した。
- 再実行したfocusedはscanner `87 passed`、Web E2E `21 passed`。最終
  `bash scripts/verify-local.sh`はexit 0（maintenance 81、scanner 227、Web unit 174、
  Playwright 56、Ruff/format/pyrefly/Svelte check/build PASS）。
- commit `6fb5ce6`のrequired `verify`はPASS。2件のreview threadへ修正証拠を返信しresolveした。
- user systemd unitsを使ったcontrolled restartはcommand exit 0。service PID
  `3450385 -> 3667379`、Web PID `3450397 -> 3667390`、両unit active、`NRestarts=0`。
- snapshotは`dataAsOf 1786330200000 -> 1786330500000`、schema `1`、feature/ruleset `3`、
  Candidate AND条件/counts、OI 60分、Watchlist、Raw Sort、Smart Rank、VPI-Lite+を確認した。
- Past NoteとDashboard settingsのhashは不変。DuckDB writerはPID `3667388`の1つでservice
  cgroup内、app service workerも1つ、Web listenerもWeb cgroup内、orphanは0。
- service stop timeout/SIGKILLは非blocking運用残余リスクとして保持する。
