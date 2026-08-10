# Quiet Market Instrument 実装計画

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-11T05:16:48+09:00`
- 検証: `2026-08-11T05:16:48+09:00`
- 状態: `実装計画`

---

## 0. Current plan goal

`PLAN-QMI-001`は、監視専用境界を維持したまま、現行15分量倍率と同じ計算族で1時間・4時間量倍率を追加し、3時間軸から表示専用の活動phaseを算出する。正常な行品質は通常UIから消し、異常だけを具体的な日本語で示す。既存VPI-Lite+対象だけを使う活動発見laneをCandidate付近へ追加する。

15分量倍率、Attention Score、74h Candidate、category、Smart Rank計算、VPI計算・対象・threshold・主ranking非介入、Hot/Cold/Chart、Past Note、Dashboard設定は維持する。Production dependency、Private API、取引・注文・予測・通知は追加しない。

Profileは`EXECPLAN`、riskは`MEDIUM`。正本checkoutは`/home/tn/projects/prep-watchdeck`、branchは`ai/quiet-market-plan-sync-20260810-2232`、開始HEADは`79f5e8d939dddb3948ead270c2eff7a1350daab2`。

## 1. Current repository audit

### 1.1 ZIPとの差異と判断

- ZIP baseline `2b5bfd5`より現行Repoは新しい。Candidateの連続4列surface、560px以下のautomatic activation tabs、15分metadata、Watchlist分類、連続Inspector、`補正順位`、`市場活動`表示は既に`aeb0d9c`/`046c9af`とPR #3で実装済み。再実装しない。
- ZIPの`apply-to-repo.sh`は対象directory不存在を前提とする。現行directoryとliving planを上書きするため実行せず、checksum PASSのappendicesだけを追加し、両living planを現行Repoへ読み替える。
- 計画上の`domain/screening/pipeline.py`と`tests/test_rankings.py`は存在しない。現行責務は`screening/pipeline.py`と`tests/test_rankings_contract.py`。
- `.codex`には今回用plan schema/templateがなく、過去の`.codex/SP_STATE.md`だけがある。今回の正本にはしない。
- 現行`volume_ratio_by_timeframe()`は15mだけ有限値、1h/4hは`None`。rowにactivity phase fieldはない。
- 現行DashboardはWatchlist/Selected detail/Smart Rankで`OK`品質を表示する。VPI panelは全benchmark/targetを列挙し、発見state・coverage・empty/unavailableを分離していない。
- `dataQuality -> riskTag -> category`は`build_risk_tags()`と`choose_category()`、Candidateは既存category/74h gateで制御される。新しい品質gateは追加しない。
- 通常履歴は74h契約用に1177本を保持し、4h倍率に必要な`baseline 288 + window 48`本を満たす。停止条件には該当しない。

### 1.2 実装契約

- 量倍率windowは15m=3本、1h=12本、4h=48本。現在windowを除いたrolling同長windowの末尾`baseline_window_bars`件の中央値を分母とし、`volume_ratio_floor_usdt`をfloorに使う。
- 15mの現行値をgoldenとして保持する。5m/24h/74hは`None`のまま。
- activity phaseは`UNKNOWN -> COOLING -> SUSTAINED -> EXPANDING -> BURST -> NORMAL`の順。内部値は`BURST | EXPANDING | SUSTAINED | COOLING | NORMAL | UNKNOWN`。
- phaseは方向・売買推奨・Score・category・rankingを意味しない。
- VPI laneは既存summary sidecarのみを分類し、`EARLY_ACTIVITY/ACTIVE_MOVE`を活動増加、`THIN_VOLATILITY/SINGLE_BAR_SUSPECT`を要注意として各score降順最大5件。現在のWatchlist表示条件で選択できる対象だけを操作可能にし、対象0、表示条件該当0、valid該当0、全件判定不能を別表示する。
- snapshotはadditive optional field `activityPhase`をrowへ追加する。`featureVersion=4`、`rulesetVersion=3`、`schemaVersion=1`。

## 2. Baseline evidence

| 検証 | cwd | 結果 |
|---|---|---|
| Git status/branch/HEAD | Repo root | exit 0、clean、専用branch、HEAD `79f5e8d` |
| ZIP checksum | Windows temp extract | exit 0、全manifest file PASS |
| Scanner focused | `apps/scanner-core` | exit 0、59 passed |
| Web focused unit/check/build | `apps/web` | exit 0、25 passed、0 errors/warnings、build PASS |
| Full local gate | Repo root | exit 0、pytest 236、Web unit 183、Playwright 59、maintenance/lint/type/check/build PASS |
| Web performance | `apps/web` | exit 0、2 passed。hot p95 1.9ms、Raw Sort p95 29.6ms、Cold max 56ms |

Windows共有側の最初のWeb baselineはLinux用`node_modules`を解決できずexit 1だった。source変更はなく、Linux正本で同一commandを再実行してPASSした。この失敗記録は保持する。

## 3. Acceptance criteria

| ID | 状態 | 条件 / 検証 |
|---|---|---|
| AC-QMI-001 | passed | 専用branch、開始HEAD、clean tree、AGENTS/DESIGN/skill/ZIPを証拠化。 |
| AC-QMI-002 | passed | Markdown/JSON living plan、appendices、handoffを同期。JSON parse、metadata/link、diff check exit 0。 |
| AC-QMI-003 | passed | package/lock差分なし、monitoring-only boundary PASS、Private/trading API差分なし。 |
| AC-QMI-004 | passed | `test_volume_ratio_timeframes_keep_15m_golden_and_add_hour_windows`とfixture E2Eで15m値を再証明。 |
| AC-QMI-005 | passed | 3/12/48本window、exact baseline sample、不足/nonfiniteの`None`をscanner focusedで証明。 |
| AC-QMI-006 | passed | priority/category実装は無変更。1h/4h Candidate volume ranking空のcontract test PASS。 |
| AC-QMI-007 | passed | 全phase、優先順、None/NaN/Infinity UNKNOWNのparameterized test PASS。 |
| AC-QMI-008 | passed | feature 4 / ruleset 3 / schema 1、Live/Fixture/schema/generated typeのfocused testと再生成比較PASS。 |
| AC-QMI-009 | passed | OK非表示、`一部データ不足 / 更新遅延 / 判定不能`をunit/E2Eで証明。 |
| AC-QMI-010 | passed | stale/partial/missing fixture E2Eと既存74h gate tests PASS。新しい品質gateは追加していない。 |
| AC-QMI-011 | passed | Desktop Candidate連続4観点をfocused/full E2Eと1440px screenshotで再検証。 |
| AC-QMI-012 | passed | Mobile automatic tabs、ARIA/keyboard、4 tabs、selection保持をresponsive E2Eと390/320pxで再検証。 |
| AC-QMI-013 | passed | Watchlist category、15m倍率、phase、異常品質、3 viewport overflow 0を証明。 |
| AC-QMI-014 | passed | Inspectorの15m/1h/4h、phase、OI、74h、理由をE2Eと3銘柄実測で証明。 |
| AC-QMI-015 | passed | VPI Target限定、coverage、分類/sort/limit、4 empty状態と表示条件外targetの非操作化をunit/E2Eで証明。 |
| AC-QMI-016 | passed | VPI score/対象計算とSmart Rank algorithmは無変更。Hot非再計算と品質補正理由E2E PASS。 |
| AC-QMI-017 | passed | focused、check/build、E2E 59、performance 2、review修正後full gate 249/186/60 PASS。 |
| AC-QMI-018 | passed_on_commit | DESIGN/current docs/ADR/plans、visual evidence、final diff、未解決P0/P1なし。対象fileだけを含む本commit自身で完了し、正確なHEAD/cleanはignored stateと最終報告へ記録する。 |

## 4. Checkpoints

1. `CP-QMI-001` completed: Repo/ZIP/current implementation/baselineを監査。
2. `CP-QMI-002` completed: appendicesと両living planを現行Repoへ同期。JSON/docs/diff gate PASS。
3. `CP-QMI-003` completed: 最小RED後、15m互換の汎用window ratioと1h/4hを実装。
4. `CP-QMI-004` completed: activity phase、DTO/schema/fixture/versionを同期。
5. `CP-QMI-005` completed: 品質label/helperと正常品質非表示を実装。
6. `CP-QMI-006` completed: Watchlist/Inspectorへ倍率・phaseを追加。既存Candidate/tabsを再検証。
7. `CP-QMI-007` completed: VPI discovery helper/unit/panelを追加し既存detailを維持。PR #5 reviewで判明した表示条件外targetのno-opを最小修正し、選択可能targetだけをlaneへ残した。
8. `CP-QMI-008` completed: focused/full/performance gate PASS。
9. `CP-QMI-009` completed_on_commit: 1440/390/320 visual QA、docs/ADR/final diff、選択的local commit/clean。

各checkpointは関連ACの再現証拠が揃うまで完了にしない。source確定後にfull gateとperformanceを再実行し、その後sourceを変えた場合は影響focused/full gateを再実行する。

## 5. Prior completed UI wave evidence

既存living planの履歴を保持する。前wave `PLAN-QUIET-MARKET-INSTRUMENT-001` revision 4はAC-UI-001〜018 PASS、CP-001〜013 completed。実装commitは`aeb0d9c`と`046c9af`、PR #3 mergeは`ce719dd`、DesignMD cleanup PR #4 mergeは`8a17b68`。前wave full gateはpytest 236、Web unit 183、E2E 59。visual evidenceは`/home/tn/.local/share/prep-watchdeck/tmp/quiet-market-instrument/final/`。この証拠は今回のAC-QMI-011/012のbaselineとして再検証するが、新しいACの代用にはしない。

## 6. Stop / rollback / scope

停止条件は15m golden変化、通常履歴不足、VPI対象拡張/計算変更の必要化、Score/category/ranking変更の必要化、production dependency、Private/trading API、性能budget超過、320/390px overflow、無関係差分衝突、同一原因3回連続未解決failure。

rollbackは今回commitをrevert可能なadditive field/UI差分に保つ。DB migration、runtime state mutation、service restart、deploy、push、PR、mergeは行わない。

## 7. Final verification evidence

| 検証 | cwd | 結果 |
|---|---|---|
| Scanner focused | `apps/scanner-core` | exit 0、36 passed |
| Web unit | `apps/web` | exit 0、27 passed |
| Web focused E2E | `apps/web` | exit 0、59 passed |
| Web check/build | `apps/web` | exit 0、0 errors/warnings、build PASS |
| Full local gate | Repo root | exit 0、scanner 249、Web unit 186、Playwright 60、maintenance/Ruff/Pyrefly/check/build PASS |
| Performance | `apps/web` | review修正後exit 0、2 passed。Hot apply p95 3.7ms、Raw Sort p95 19.3ms、Cold 51.6ms、transport budget内 |
| DesignMD | Repo root | exit 0、errors 0 / warnings 0 / infos 1 |
| Docs/JSON/schema | Repo root | JSON parse、metadata/link 17、schema再生成cmp、generated Web type、diff check PASS |
| Visual QA | isolated port 4190 | 1440/390/320pxでscrollWidth=clientWidth、Candidate/VPI/Watchlist/Inspector/補正順位/銘柄注記、mobile 4 tabs PASS |
| 3銘柄選択 | isolated fixture | ALT 58/73/60ms、NEWALT 39/43/43ms、THIN 33/34/34ms。各row phaseとInspector 1h/4h/phaseを記録 |
| Sentinel | production state read-only | Past Note `2240c8ad...b24001`、Dashboard settings `e1e57eb1...4fb7e`でbaseline一致 |

Full gateの途中失敗は2回とも今回差分のformat gateだった。1回目は`domain/dto.py` import整形、2回目は
`test_domain_features.py` formatでexit 1。局所整形後、同じfull gateを最初から再実行してexit 0を得た。
一時previewは親停止後にVite子が残ったため、port 4190を保持する今回のPIDだけを確認して停止し、listener/orphan 0を確認した。production processには触れていない。

PR #5 review thread `PRRT_kwDOTqwzwM6YBKtf`は、filter後の`visibleRows`に存在しないVPI targetを
選択buttonとして表示できる不整合を指摘した。unit RED（旧実装は1 failed）後、lane入力を現在選択可能な
symbol集合で絞り、専用empty stateを追加した。unit 9 passed、home E2E 24 passed、full gateとperformanceを
source修正後に再実行して上記GREENを得た。VPI producer、対象判定、score、rankingは変更していない。

Visual evidenceはGit外の
`/home/tn/.local/share/prep-watchdeck/tmp/quiet-market-instrument-activity/final/`にある。
小fixtureのMobile Watchlistは400-row reachability用の既存bounded scroll高を保つため空きが大きいが、
overflow/clip/操作不能はなく、今回差分起因のP0/P1ではない。

## 8. Final status

- Current checkpoint: `CP-QMI-009 completed_on_commit`
- Mandatory passed: `18 / 18`（AC-QMI-018はこのplanを含むcommit自身で成立）
- Final head: `this plan commit itself`。parent HEADは`3a8bfecc1d6ca087d70bb07b55facf0a9fe78dbf`。正確なcommit/treeはignored `.ai-work/state.md`と最終報告へ記録する。
- Goal gap: なし。
- Remaining work: なし。
- Unresolved P0/P1: なし。
- Residual risk: old feature 3 snapshotではoptional `activityPhase`がないためUIは`判定不能`。production反映・restartはmerge後の正式運用手順で別証拠化する。
