# P1 Candidate / OI 契約修正 実装計画

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 検証: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 0. メタデータ

- Plan ID: `PLAN-P1-CANDIDATE-OI-001`
- Revision: `2`
- Target repo: `tsutomu-n/prep-watchdeck`
- Baseline commit: `47839c33466f970f1c31d665df73e5d24ba77e6c`
- Canonical path:
  - `docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.md`
  - `docs/plans/active/p1-candidate-oi-contract/IMPLEMENTATION_PLAN.ai.json`
- Current status: `plan_only`

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

### Unknowns to resolve in CP-001

- 現HEADとbaseline差分
- concrete DuckDB service store path/API
- 既存OI history tableの有無
- repository plan template/schemaの有無
- current reconnect test coverage
- ticker freshnessの既存契約。なければ、既存service freshness constantを再利用するか明示的な最小契約をdecision logへ記録する。

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
