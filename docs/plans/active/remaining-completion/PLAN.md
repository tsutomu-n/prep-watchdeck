# 残件の実装計画 — 追加調査を反映した実行版

timestamp="2026-10-11(日)_14:31 JST"
- 作成: `2026-10-11T13:53:08+09:00`
- 更新: `2026-10-11T14:31:19+09:00`
- 検証: `計画と保存済み実データの照合。実装検証は未実行`
- 状態: `実装計画`
- 実行状態: `IN_PROGRESS`。ユーザー指示「実装・本番変更」により実装と対象unit反映を開始。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. この計画はprimaryが段階的に実行する。agentの追加・並列writeを前提にしない。

**Goal:** 現行の裁量支援workspaceで、説明不能な収集・監視異常を診断し、確認できるidentityと履歴だけを使った運転受入、容量管理、outcome経路、本人の実機受入を成立させる。長期評価は事前固定した仕様で完了する。

**Architecture:** 現行のMarket単一writer、Rankingの参照価格、Attentionのread-only入力と専用stateを維持する。検証済みの未採用Recovery・受入支援を選択的に統合し、current runtimeを保った新release/map/bundleを作る。研究とoutcome処理は隔離したcopy・出力で行い、既存journalや凍結policyを書き換えない。

**Tech Stack:** 既存Python3.13 / uv / PostgreSQL / SQLite / Pydantic / Polars、Bun / SvelteKit / Playwright。新しい外部provider・依存・常駐serviceの追加は前提にしない。

**Spec:** 最新指示「実装・本番変更」、承認済み実装計画と追加調査依頼、今回のuser指示「残りの中心を片付けていこう」「まずは調査」「計画を考えて」「必要なら追加調査」、現行AGENTS、製品境界、既存MEXC段階受入・Attention受入条件。調査標本は`/home/tn/watchdeck-local-archive/remaining-completion-plan-20261011-1316/observations.json`。完成度の主観的な8割を、受入率へ換算しない。

## Global Constraints

- 元workspaceの未commit4件、selection、workspace、判断履歴、Past Notes、旧release/mapを保全する。
- 現行source基準は `6cb347c780eb7536c2ff1cfb024f9e7822733f47`。原workspaceは別checkout。最新verified sourceを再確認し、新しい `ai/<task>-YYYYMMDD-HHMM` branchと専用worktreeで実装する。
- CI・PR・main mergeは使わない。実装差分だけを必要な検証後にcommit。push、対象unitの切替、backup、live repairは操作・対象の既存承認と最新指示を確認して実行する。最新のuser指示「実装・本番変更」はこの計画の実行と対象runtime反映の承認。
- Market以外のwriterをlive Market DBへ接続しない。JustPassの5432・DB・container・volumeへ接触しない。
- 未確認identity、quantity、Widget、価格倍率を昇格しない。null / status / reason、exact ID/version、source時刻、finality、provenanceを維持する。
- `partial=0`、全銘柄審査完了、利益・候補優位性を成功条件にしない。対応不能・ゼロ基準・実測欠損を明記した有効応答は許容するが、期待値の緩和やunknownの隠蔽はしない。
- 現行v1、既存frozen family、既存研究journal・登録ruleは不変。正式評価と途中診断を区別する。
- 本番のevidence削除・自動prune・DB downgradeはこの計画の初期実装に含めない。archive/restoreのcopy検証を先に行う。
- Attentionのactual multi-captureは現行受入対象の実市場入力と別機能。ATT-124/125はこの計画へ混ぜない。

## 調査で確定した基準

| 境界 | 観測・既存証拠 | 解釈 |
|---|---|---|
| runtime | Market `ef2f57e`、Ranking/Attention `c805056`、Web `1dec94d`、map `8e874654f920c73bded2fd40` | 混在は現在の意図した配置。単一SHAの配置済みとは言わない |
| 元契約 | 1147件。Aster453 / Bitget466 / Hyperliquid178 / MEXC50 | mapとのversion不一致・未登録・削除は観測時0 |
| Discovery | 13:16標本は618件中532件判定、82 identity_ineligible、4 comparison_unavailable | 件数は更新で変わる。42 unsupported＋40 MEXC reviewがidentity不適格の中心 |
| map資格 | verified536 / unsupported42 / review40、quantityReview4、widgetReview43 | `qualificationComplete=false`。構造整合性やnative分類の審査成功で代用しない |
| 比較不能 | ASRの保存済み比較窓で前日turnover=0、ratio=`no_baseline` | 不足履歴とは別。backfillで正の基準値を捏造しない |
| collector | 11:00–13:09の129周期にsucceeded110 / partial19 | release/map変更をまたぐ診断標本。新2h受入の代替ではない |
| 監視 | 13:00、13:06にl1_unavailable。13:09、13:16の直接確認は終了0 | map不一致の再発ではない。継続failureと一周期partialを区別する |
| 原因の追加確定 | 13:00 collectorはMEXC partial。13:06はMEXC ready、Aster partial。SXTUSDTのbidPrice=0、保存best_bid=null、Aster453件中452 ready/1 partial | 13:06をMEXC Funding問題として修正しない。Asterの当該rowは正しくpartialで、bidを補完しない |
| 履歴の更新境界 | 13:00/13:06のMEXC minute stateは追加調査時には50 ready。独立Funding writerは同じ既存bucketの値とstatusを後から更新する | collector終了時の状態と後続Funding更新を別に保存する。現在のminute stateを当時のavailabilityへ読み替えない |
| 監視の分類 | freshなl1 partialでもerrorCode=venue_partial_failureによりl1_unavailableになる。collector partialとnative partial自体には既存warning経路がある | 取得全体の停止と、説明可能な対象別不良を分ける。品質不良・stale・対象除外の証拠は保つ |
| Recovery | 完了標本で通常Recovery remaining45、endpoint remaining6。稼働中標本はnullの場合もある | 同じ窓・generationの完了証拠で再監査する。起動時の0 target/nullを完了と呼ばない |
| 研究 | 1440 receiptsを保存。replay_valid=true、candle欠落2/state欠落5、qualified_for_ab=false | 原本の品質不足を保持。終了後処理は2分timeout、daily summary/resultsなし |
| Attention | 約3200世代、約640 evidence世代、固定policy16、outcome0 / evaluation run0 | 30日評価前に実outcome入力経路を通す必要がある |
| 容量 | Attention全state約11.97GiB、host空き約259.5GiB、専用PG logical約9.95GiB | 直ちに容量停止が必要な根拠なし。PG物理directoryは権限不足、全量へ補完しない。30日容量は未受入 |
| 未採用資産 | `55edb36`のRecovery/audit/reconciliation/bundleはlocal検証済み。bundle mapは旧`9b411...` | `55edb36`はsource基準のancestorではない。旧bundleの丸ごと配置・旧map復元をしない |

Bitgetの既存history-candles取得で429を観測した。[現行公式契約](https://www.bitget.com/docs/catalog/classic-contract-market/classic-contract-market)の同endpointは20回/秒/IP、最大200件を示す。追加回復はこの制約と既存foreground取得を考慮し、制限内の限定処理にする。数値は現在のAPI仕様であり、実装開始時も確認する。

## 実装を分ける単位と順序

6つの到達段階を、8つの独立して検証・commitできるまとまりに分ける。primaryが順に統合し、同時writeや追加agentを前提にしない。既存計画のTask番号は下記の対応を保つ。

| 単位 | 作るもの | 前提 | 終了判定 |
|---|---|---|---|
| A / Task1前半 | 周期終了時の理由診断と監視分類 | 最新source・retained rawを固定 | Aster単一row不良、Funding限定partial、全体取得不能、未知原因が別結果になる |
| B / Task1後半 | 容量reportと隔離copy復元 | Aの診断を待たず実装可能 | 測定範囲・空き・増分・復元checksumを確認。30日forecastは期間不足ならnot_validated |
| C / Task5前半 | 保存済み研究の有限な終了処理 | 1440 receiptsと原本hash | COMPLETE / INELIGIBLE / evaluation NOT_RUNを同時に正しく示し、timeout後も再開可能 |
| D / Task2 | Recovery資産の選択的統合とidentity審査 | A、現行map、Bの復元手順 | scope全件に処理結果。採用資格と未対応・未確認を明示した新bundle |
| E / Task3 | 50件で新しい2時間運転受入 | D、反映対象と品質基準の固定 | 7200秒の同一release/map標本と性能・鮮度・保全の証拠 |
| F / Task4 | 100件で24時間運転と容量受入 | E、追加50件の再照合 | 実際の24h運転、通常maintenance、増分と容量余裕を確認 |
| G / Task5後半 | outcome export・隔離評価・固定protocol | B、実データ入力の資格 | 15/60分の実outcome経路を通し、30 UTC day blocksの起点・終点・formal lookを固定 |
| H / Task6 | 本人の実機確認・closeout | 安定した画面。早期に着手可能 | IME/focus/Chart往復/下書き/再開を本人が確認。未確認は残す |

最初のsource実装は **A → B → C**。D→E→Fが対象拡大の経路。Gの入力経路準備とHの実機確認は、独立した範囲で先に進める。30日評価の待機期間に他の実装を止める必要はない。2h/24h/30 UTC day blocksは必要な実測期間で、実装作業時間の見積りではない。

実装開始時は最新source、元workspace4件、既存stage/index、active writer、unit/map/保護stateのhashを再確認する。実装用branchを作る時点でcanonical active planをrepo規則の場所へ取り込み、この外部計画のhashをcheckpointへ記録する。既存の未完了planはその履歴を保って照合し、未採用の古い成果物をcurrentと扱わない。

## 追加調査の証拠

- `/home/tn/watchdeck-local-archive/remaining-completion-plan-20261011-1316/additional-persistence-investigation.json`: collectorのVenue別statusとMEXCの現在のminute state。両者は同じ時点の状態ではない。
- `/home/tn/watchdeck-local-archive/remaining-completion-plan-20261011-1316/additional-minute-state-investigation.json`: 13:06のAster SXTUSDT 1件partial、bid欠測。OI nullは既知のunsupportedとして別扱い。
- `/home/tn/watchdeck-local-archive/remaining-completion-plan-20261011-1316/additional-aster-raw-investigation.json`: bidPrice=0、raw payload hashと3 endpointの時刻。ticker closeTimeを現在時刻に置換しない。その意味の追加解釈をしない。

## Review Focus

1. Funding限定partial、Asterのbid不良、全体取得不能を分ける。fresh cycleでも不良rowをreadyへ変更せず、未説明原因・不正時刻・無入力をfailureとして残す（Task1/A）。
2. catalog更新・native version変更・修復後のhistorical candleに、過去のavailabilityや誤った同一性を与えない（Task2/3）。
3. SQLite backupとimmutableファイルのcopyで異なるgenerationを混ぜない。Ranking/Attention間にtransactionはないためcutoffと各map/generationをmanifestで照合する。不一致・copy不完全は採用しない（Task1/B、Task5/G）。
4. quality不適格・停止signal・timeoutで研究の正常完了や評価PASSを偽造しない（Task1/5）。
5. 30日途中の結果・seed変更・異なるeligible集合で候補優位を選ばない。cutoffと正式判定回数を事前固定する（Task5）。

## 順序と並行できる範囲

`Task1 → Task2 → Task3（50件2h）→ Task4（100件24h）`

容量測定と本人の実機確認はTask1以降、安定した範囲で進められる。Task5の既存研究の終了処理修復・outcome経路の隔離検証・評価protocolの設計はTask1/2と独立して進められる。正式30日評価の起点は、対象・policy・評価条件を固定し、入力経路が受入済みになった後とする。

### Task 1: 収集理由の診断、容量確認、受入基準の固定

**責務:** 監視を安心して解釈でき、後続の運転が合否判定可能になる状態を作る。

**既存対象:** `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/market_store.py`、同じMarket packageの`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/service.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/artifacts.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/sources/mexc_l1.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/sources/mexc_funding.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/sources/aster_l1.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/scripts/market/check-data-operations.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/tests/test_market_store.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/tests/test_data_operations_monitor.py`。

**作成予定・未作成:** 実装branchへ相当する `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/scripts/ops/check-runtime-capacity.py` と対応する最小test。監視結果は専用の観測出力rootへ保存し、business stateへ書かない。

**Interfaces:** collector metricsの既存JSONBに `persistedQualityCountsByVenue`、`persistedReasonCountsByVenue`、`persistedDiagnosticExamples` を追加する。最終persist/join後の結果を数え、examplesは各Venue最大8件のexact ID/version、reason、欠測field名とsource時刻に限定する。collector runの同じtransactionへ保存して後続Funding更新で変更しない。原本payload・秘密を含めない。capacity reportは `sampledAt`、`stateBytes`（SQLite/WAL/artifact内訳）、`filesystemAvailableBytes`、`measurementCoverage`、`observationDurationSeconds`、`projection`（期間/増分/仮定）を持つ。24h未満の外挿には診断用と明示し、受入済み30日forecastを生成しない。既存status・databaseBytesの意味を変更しない。

- [ ] final Funding join、quantity/native version照合、persistenceの境界で、実際に保存した状態の理由・件数・少数の診断IDをcollector metricsへ記録する。取得時rawのFunding理由を保存時の理由として流用しない。既存JSONBを使い、DB migrationを前提にしない。
- [ ] 独立Funding更新で元bucketのstatusが変わっても、collector終了時の診断は不変とする。後続rawのobservedAt/nativeVersionId/contractVersionを辿れることを確認し、旧availabilityを上書きしたかのような研究証拠を作らない。
- [ ] 最小回帰 `test_persisted_diagnostics_preserve_final_reason_and_bound_examples` のparameterized caseでFunding-only、Aster bid=0、native version変更、複合原因とVenue上限8件を区別する。既存Funding store回帰に、後続Funding更新後もcollector diagnosticsが不変というassertionを加える。`test_capacity_projection_requires_valid_sample_period` で短期間/不足sample/取得不能を受入forecastにしない。既存の正常source/monitor testsを維持する。
- [ ] 13:00 MEXCのFunding限定不良と13:06 Aster SXTUSDTのbid=0をretained rawで再現する。原本を変えず、対象別partialと取得全体の停止を別に報告する。bid/時刻/OIを補完しない。
- [ ] 監視はfreshなpartial＋既知のvenue_partial_failureだけを、完全な診断件数と対象別不良を伴う条件で分類する。対象別不良は品質失敗として残し、stale/unavailable、未知error、identity drift、診断欠落、当該Venueの利用可能入力0はoperational failureとする。診断を必要とする場合だけ、collector artifactへoptional bounded diagnosticsを追加しschema/型を生成する。旧readerの互換性を先に検証する。
- [ ] `test_partial_cycle_is_reported_without_masking_unavailable` を既存monitor testへ追加する。Aster 452 ready/1 known partialを説明付きpartial、stale/全体取得不能/未知理由/診断欠落をfailureとする。exit0は対象全体の品質PASSを意味しない。旧assertionを削除する変更で帳尻を合わせない。
- [ ] SQLite＋WAL＋immutable、Market archive、PG logical/取得可能な物理量、host全体の空き推移を記録する。取得不能はunknown。24hの増分と長期推計の前提を分ける。
- [ ] archive/readback/restoreを隔離copyで通し、checksumと参照generationを照合する。本番削除はしない。新規蓄積停止条件は現行の空き50GiB、直近増分の7日分確保を維持する。
- [ ] 関連pytest→Ruff check/format→package Pyreflyを通し、このtaskの差分だけをcommitする。

**Gate:** 説明不能な監視異常を既知の警告へ置換していない。取得全体の稼働と対象別品質の判定を分け、known partialをPARTIAL/PASS WITH ISSUESとして明示する。全理由・件数・鮮度・versionを追跡できる。容量は全体空きとcomponent内訳の範囲を区別し、隔離復元が成立する。

### Task 2: 現行sourceへRecovery資産を統合し、identity/履歴の残件を閉じる

**責務:** 回復可能な欠損と回復不能・未確認を切り分け、実データに対して監査可能な状態を作る。

**再利用対象:** `55edb36`の`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/candle_gap_audit.py`（待統合・現行では未作成）、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/candle_gap_reconciliation.py`（待統合・現行では未作成）、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/recovery_evidence.py`（待統合・現行では未作成）、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/acceptance_evidence.py`（待統合・現行では未作成）、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/acceptance_bundle.py`（待統合・現行では未作成）と既存tests/CLI、保管済み受入helper。現在のsourceへ適用する時点で全差分を確認する。

**現行対象:** `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/candle_recovery.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/candle_endpoint_recovery.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/candle_recovery_state.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/service.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/scripts/ranking/prepare-mexc-map.py`、Ranking mapping/models、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/ranking-core/data`。

**Interfaces:** history auditはscope・DB identity・exact native version・window・checksumを固定。reconciliationは旧証拠と新証拠を混ぜず、追加時刻とreadbackを持つ。新bundleは新commit/map/helper/unit bindingsのSHAとrecoveryNotBeforeを持つ。

- [ ] source baselineへ必要部分を選択的に統合する。Phase Aのhistory-limit対応、下書き保護、OI unsupported、Discovery coverage表示を保つ。旧branchの丸ごとmergeで逆戻りさせない。
- [ ] 40 MEXC reviewをnative分類、固定reference、quantity、Widgetに分ける。42 unsupportedは既存根拠を尊重し、新しい肯定根拠がある対象だけ再審査する。
- [ ] fresh公式catalogとexact契約/倍率を確認できる対象だけを採用する。reference不存在・未確認なら理由を残す。native-onlyと外部reference資格を同一視しない。
- [ ] quantity4 / Widget43の各残件を表にし、確認可能なものだけ閉じる。残るものは機能を限定し、`qualificationComplete=false`と受入範囲を維持する。`validate-map --require-reviewed`の失敗をPASSと呼ばない。
- [ ] 固定窓でread-only auditを実行し、missing / provider history limit / definition証拠不足 / no_baselineを区別する。native definition/validityを確認したwindowだけ、Marketの既存単一writer内で限定回復する。
- [ ] 原本・修復履歴・変更前後件数・source hash・finality・追加時刻を保存し、同一scopeの再scan/readbackで照合する。後日回復を過去の研究availabilityへ遡及させない。
- [ ] 局所回帰と当該package必須check、map evidence/schema生成checkを通す。new source/map/bundleを追跡対象のみで再生成し、混在sourceを保った配置案と切戻しを具体化する。

**Gate:** すべての対象に処理結果と理由がある。eligibleの履歴と定義が一致し、未資格はexcluded/reviewとして明示される。古いmap `9b411...`や古いunit bindingsをcurrentとして採用しない。全map資格PASSと、機能を限定した運用受入を別に報告する。

### Task 3: 現行50件の新しい2時間運転受入

**対象:** Task2のtracked release、immutable map、再生成したstage50 observer/Funding capture/helper/policy、正確なunit bindings。copy archiveの`55edb36`版helperを参考にし、現在のrelease/mapへ再bindする。

- [ ] 元workspace/control、対象unit、Market writer数、DB/SQLite backup、既存release/mapを保全し、反映対象とhashを確定する。互換reader→Market writerの順を守る。
- [ ] 承認対象のunitだけへsource/mapを反映する。live DB変更は必要性が確認されたものだけ、別の具体的操作として扱う。
- [ ] 採用後のrecoveryNotBeforeと完了Recovery証拠を確認し、新しい7200秒のobserverを開始する。中断・旧source・異なるmapの標本を連結して2hにしない。
- [ ] 既存scopeのcycle<60s、input freshness<=150s、summary/detail p95<=1s、OOM/予期しないrestart0を確認する。Attention anonymous＋kernel peak目標は768MiBの80%以下。
- [ ] Funding expiry/settlement、WS gaps、429、recovery backlog、理由別partial、数量・単位・時刻を確認する。既存settlement例外は最大90秒の厳密な二枝の根拠付き条件だけ。一般expiry/取引失敗/identity driftへ広げない。
- [ ] source、native/reference、snapshot/journalのhash、selection/workspace不変、Webと実Tailnetのread-only表示を照合し、50段階の結果を確定する。

**Gate:** 未説明failure/open episodeなし。既知の対象別不良は機能を限定してPARTIAL/PASS WITH ISSUESとして保存し、受入対象を後から縮小しない。既知の品質制限は件数・理由・適用機能を明記。逸脱なら進行停止して保存済み証拠から診断し、新しい起点で受入をやり直す。100切替を自動連鎖させない。

### Task 4: MEXC100件への更新と24時間・容量受入

**既存対象:** `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/sources/mexc_evidence.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/data/mexc-reviewed-20261010`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/scripts/ranking/prepare-mexc-map.py`、MEXC WS/共有budgetと既存stage100 helper。

- [ ] 審査済み100件bundleを再利用し、fresh official catalogに照合する。既存50を保持し、新50のexact native versionでimmutable mapを生成する。基準はTask3の最新版で、古い`d81614e`releaseの再配置ではない。
- [ ] 新規契約のcrypto/USDT/linear、quantity、Funding interval、価格時刻とsourceを確認する。未確認を推測で足さず、native-onlyをreference比較へ昇格しない。
- [ ] 25symbols/connection、100件で4 WS、共有HTTP8 calls/2秒・固定laneを維持し、通常foreground/selected/chartへの影響も確認する。
- [ ] 変更箇所のtestsとmap/schema/型checkを行い、cross-package release gateを1回通す。必要な修正後以外はgateを反復しない。
- [ ] 100件を承認対象へ反映し、新しい24時間通常運転を開始する。通常maintenance、settlement、endpoint recoveryを含める。
- [ ] Task3の性能・鮮度・理由・保全条件に加え、SQLite/WAL/immutable/Market/host空きの24h増分を測る。30日運転の推計＋50GiB空き、archive/restoreのstaging・outcome増加分も含めて判定する。

**Gate:** 100件の実運転と容量の暫定受入。24h推計を30日実測と呼ばない。native-onlyが増えた場合のDiscovery/Attention coverageも公開し、分母を減らして改善を装わない。

### Task 5: 既存研究の終了処理、実outcome入力、正式評価protocol

**既存対象:** `/home/tn/.local/share/prep-watchdeck-research/20261009-bitget-btc-v1-1550/`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/research_cli.py`と`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/research`、Attentionの`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/attention-core/src/prep_watchdeck_attention/outcomes.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/attention-core/src/prep_watchdeck_attention/evaluation.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/attention-core/src/prep_watchdeck_attention/models.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/attention-core/src/prep_watchdeck_attention/cli.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/attention-core/src/prep_watchdeck_attention/storage.py`、既存research/outcome/evaluation tests。

**作成予定・未作成:** `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/apps/market-core/src/prep_watchdeck_market/research/finalizer.py`、`/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/scripts/attention/export-outcome-input.py`、familyを参照するimmutable評価protocol。新しいformal protocolは既存CandidatePolicyのhashを書き換えない。

**Interfaces:** capture completion、quality eligibility、evaluation statusを別fieldで報告。offline入力は既存`attention-outcome-input-v1`の`mapVersion / bars / native`へ接続する。protocolはfamily hash・対象範囲・開始/終了cutoff・formal look回数1・seed/bootstrap数・共通eligible診断・欠測/訂正方針を事前固定する。

- [ ] 1440 receiptsとsnapshot/quality/trialのhashを確認し、原本を保った新しい隔離outputへ終了処理を再実行する。失敗したhookの一括再起動や24h再取得を先に行わない。
- [ ] capture本体の終了3と、終了後のtimeoutを別に記録する。品質不適格なら評価NOT_RUN＋reasonを出す。欠落2/5を埋めたり、この元studyを評価PASSへ変更しない。
- [ ] `finalize_capture(input_root: Path, output_root: Path, *, deadline_seconds: int) -> dict[str, object]` を新finalizerの入口とする。出力は原本と同一/内包/被包含を拒否し、原本manifestとprocess completion証拠を固定する。capture_complete/quality_eligible/evaluation_status/finalization_statusを別fieldにする。期限切れはfinalization INCOMPLETEとphase/checkpointを出し、既存成果物hashを照合して再開する。品質不適格なら重いA/B評価へ進まない。終了処理を2分hookから、期限・再開・原本hash・atomic結果を持つ有限処理へ整理する。既存の正常研究testに加え、`test_quality_exit_three_is_complete_but_ineligible` と `test_finalizer_deadline_preserves_input_and_reports_incomplete` を最小回帰とする。重複起動、signal、count不足は既存caseを再利用する。
- [ ] Ranking/Marketの許可済みread-only入力から、outcome素材を少なくとも日次で隔離exportする。Rankingの現行retentionは `4 * 1440 + 1` 分であり、30日後まで元minute barsが残るとは仮定しない。Attention writerはactive Ranking DBへ接続せず、専用copy＋offline fixtureを使う。export helperだけがread-onlyのSQLite online backupを専用出力へ作り、稼働DB/WAL/SHMの単純file copyを使わない。
- [ ] `export_outcome_input(ranking_copy: Path, attention_copy: Path, output_root: Path, *, map_version: str, after_ms: int, through_ms: int) -> Path` をexport helperの入口とする。両入力はlive stateと重ならない完成済みcopy、出力はimmutable bundle。mapVersion別に分割し、closed barsとnative pointのexact identity/available時刻を照合する。未閉鎖窓、原時刻より前への丸め、重複・gap・不一致を採用しない。`FixtureBarReader`の128MiB上限に合わせ、day/map/reference群で分割しmanifestを付ける。
- [ ] 既存outcome testを再利用し、実export→既存settle/evaluate CLIを専用copyで通す。live Attention DBへ別writerを接続しない。source時刻、reference/native identity、future窓のgap、map/revision変更を保持し、計算不能はreason/nullとする。
- [ ] 実データ短窓でoutcomeが得られる対象と得られない対象を確認する。候補と3 baselineの共通eligible比較、coverage/単一Venue/理由別診断を追加する。共通集合は判断時点のinput資格で決め、将来outcomeから選ばない。`test_common_eligible_is_selected_before_outcome` を最小回帰とし、元の全体coverage guardも残す。
- [ ] 正式cutoff、判定回数1、seed=0、bootstrap_samples=2000（現行CLI既定）、K=10/20、horizon=15/60分、minimum30 UTC day blocks、minimum_coverage=0.8、maximum_coverage_regression=0.05、minimum_practical_delta=0.1をprotocolへ事前固定する。最終cutoffは観測開始のUTC境界と同時に確定し、途中結果で延長/短縮しない。既存の異種単位raw max v1は明示したheuristicとして保存し、score変更が必要なら別policyとして評価開始前に固定する。
- [ ] `test_protocol_rejects_changed_cutoff_seed_or_family` で正式protocolの改変を拒否する。日々の診断はdescriptiveとして保存する。正式評価は固定cutoffで1回、訂正版の再計算は別editionとして履歴を残す。30日中にpolicyや都合のよい停止日を選び直さない。

**Gate:** 元のcaptureの終了・品質・評価可否が確定し、outcomeとevaluationが実データ由来の隔離copyで通る。正式評価は条件成立までPARTIAL/not_run。結果がsupportedにならなくても、reject/insufficient evidenceを正しく確定できれば評価工程は完了。将来最大絶対参照returnの結果を方向・実約定・費用控除後利益へ拡張しない。

### Task 6: 本人の実機・日常利用受入と最終closeout

- [ ] Task1以降の安定した画面で、本人のPC/スマホ、日本語IME候補窓、focus、検索・比較、Discovery→native Chart→戻る、未保存理由、再読込・再開を確認する。本人の操作と隔離browser自動化を別記録にする。
- [ ] 条件・戻り先・固定根拠が失われる具体的再現があれば、その差分だけ修正し、該当する最小E2Eを追加する。実機未確認を自動testでPASSへ繰り上げない。
- [ ] discovery、ranking、attentionの解釈とpartial理由、capacity/保存期間を日常判断で誤認しないことを確認する。
- [ ] source/local check、commit/push、production、実データ、2h/24h、30日評価、本人acceptanceを別欄で閉じる。
- [ ] 実装時にcanonical active planと既存古い台帳を照合し、現行事実をcurrent docsへ、採用判断をdecisionsへ反映する。完了したplanはtreeから削除し、未完了部分だけを再開先として残す。

## 実装時の検証commandとcheckpoint

現在の調査sourceのrootは `/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck`。下記はそのroot基準で、実装時は専用worktreeへ移して実行する予定。今回実行したcommandではない。

| まとまり | 最初の確認 | 通過証拠 |
|---|---|---|
| A | `uv run --package prep-watchdeck-market pytest apps/market-core/tests/test_market_store.py apps/market-core/tests/test_funding_store.py apps/market-core/tests/test_data_operations_monitor.py apps/market-core/tests/test_artifacts.py` | 意味ある新回帰と既存の失敗分類がPASS |
| B | `uv run --package prep-watchdeck-market pytest apps/market-core/tests/test_runtime_capacity.py`（新規予定） | 期間不足/unknown forecast、整合copyのreadback・不完全copy拒否 |
| C | `uv run --package prep-watchdeck-market pytest apps/market-core/tests/test_research_cli.py apps/market-core/tests/test_research_finalizer.py`（後者は新規予定） | complete-ineligible、deadline後checkpointと原本不変 |
| D | 既存Recovery/bundleの対応pytest、`uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py`、正本schema check | 現行mapと新bundleのexact bindings。runtime候補とtracked initial mapの結果を別に保存 |
| G | `uv run --package prep-watchdeck-attention pytest apps/attention-core/tests/test_outcomes.py apps/attention-core/tests/test_evaluation.py`＋export最小回帰 | 入力のgap/identityを保持し、既存計算経路へ接続 |

各Python変更packageでRuff check / format --check / Pyrefly。広い統合は当該package全pytest。artifact/schemaを変えた場合だけ正本のgeneratorとWeb型生成を行う。source release反映前はrepo必須の `bash scripts/verify-local.sh` を実行する。Web UIを変えないA/B/Cに新しいbrowser testを増やさない。E/Fは再bindした専用helperのschema/signatureを確認し、固定policyと実時間の証拠を保存する。

各まとまりのcheckpointにsource SHA、作業tree状態、変更対象、local result、runtime反映の有無、map/hash、未解決事項、次のgate、exact rollback対象を記録する。commitは今回の差分だけ、push/本番操作は既存承認の操作・対象との一致を開始直前に確認する。実装中に阻害された部分だけを未達として残し、独立した許可済み作業は継続する。

## 最小検証と停止条件

関連pytest/Ruff/format/Pyreflyを変更箇所ごとに実行する。Web変更があればVitest→Svelte check→build＋関連E2E。model/schema変更は正本から再生成しcheckする。最終cross-package sourceにrelease gateを1回実行し、文書metadata/links/diffを確認する。今回の調査ではこれらのsource検証を再実行していない。

実運転のgateはsource testで代用しない。2h、24h、30日はそれぞれ実際の標本期間が必要。容量不足・identity漂流・backlog/429継続・新しいsource不良・予期しないrestartがあれば100昇格やformal評価開始を止める。raw evidence、旧source、protected controlsを保持する。

切戻しはexactな追加設定とhashを確認して対象unitを戻す。現在のnative契約versionを旧mapへ無理に戻さず、必要なら直前段階registryを単一writerで再catalogし現versionで再資格判定する。DB/state/evidenceは削除しない。切戻しを実行していなければNOT_RUNとする。

## 受入の到達点

1. **運用の土台:** 理由診断・容量/復元・scope別資格・履歴auditが成立する。
2. **対象拡大:** 50件2h、その後100件24hを実際に満たす。scope外の未対応・未資格は明記する。
3. **日常利用:** 本人の実機受入が成立する。自動test成功とは別。
4. **長期評価:** 固定protocolと実outcomeで30 UTC day blocksを評価する。必要期間が揃うまで未完了。

最初に実装するまとまりはAの理由診断と監視分類、Bのcapacity report/隔離復元、Cの保存済み研究の終了処理である。そこで説明可能性と入力経路を作り、Task2の限定回復、50→100運転受入へ進む。残件すべてを一つの巨大releaseで閉じない。

## 参照した既存成果物

- `/home/tn/watchdeck-local-archive/discovery-coverage-repair-20261011-1152/FINAL_REPORT.md`
- `/home/tn/watchdeck-local-archive/phase-a-production-20261011-1101/FINAL_REPORT.md`
- `/home/tn/watchdeck-local-archive/acceptance-bundle-integrity-20261011-0825/verification-summary.json`
- `/home/tn/watchdeck-local-archive/current-state-research-20261011-0915/RESEARCH_REPORT.md`
- [/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/docs/plans/active/mexc-100-scale/PLAN.md](/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/docs/plans/active/mexc-100-scale/PLAN.md)
- [/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/docs/plans/active/attention-core/acceptance.json](/home/tn/.codex/worktrees/watchdeck-identity-recovery/prep-watchdeck/docs/plans/active/attention-core/acceptance.json)

## 実行checkpoint

timestamp="2026-10-11(日)_14:19 JST"

- A: closed artifact schema・生成型と周期診断を実装。関連46 pytest、Ruff/format、Pyreflyを通過。本番未反映。
- B: capacity初回はPG physicalのhost権限不足をunknown、30日forecastはnot_validated。SQLite online backupと3295 immutable generationのchecksum/readback完了。PG dumpと隔離restore/readback完了。現行native 1147件、minute state 12769005行を照合。
- C: 1440 observationsの原本を保全し、capture COMPLETE・quality INELIGIBLE・evaluation NOT_RUN・finalization COMPLETEを新出力へ確定。candle 2/state 5の欠測を保持。
- D以降、実測7200秒/24h/30日、本人実機は未完了。

- D/source: Recovery、取消保護、history audit/reconciliation、bundle検証を選択統合。既存履歴上限・下書き・Discovery表示を保持。Recovery等161 pytestとmonitor 23 pytest通過。固定6hのread-only auditは412920分中412744分を確認し176 gapを保存。新規Provider取得・DB変更は0。これはRecovery完了PASSではない。
