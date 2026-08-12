# ExecPlan: 74時間判定と常駐deep backfillのパージ

- 作成: `2026-08-12T17:03:31+09:00`
- 更新: `2026-08-12T22:54:50+09:00`
- 状態: `実装計画`
- Plan ID: `2026-08-12-purge-74h-deep-backfill`
- Profile / risk: `EXECPLAN / HIGH`
- Base revision: `ad3364f6e3b0c30c85469a22da3789f19d3727b9`
- Current checkpoint: `CP-06 completed`

## 0. 結論と現在地

- **Target**: 74時間判定と、それだけを成立させるCandidate gate・公開field・UI・5,885本deep
  backfillをproduction経路から除去する。deep backfillのpure componentは将来用の未接続部品として
  残してよい。
- **選択**: Cold snapshot、短期candle、直近reconcile、detail chartは今回維持する。ただし、短期指標に
  必要な383本5分足と、現行chart深度を維持する1,177本5分足を同じwindowとして扱わない。
  scanner判定とgap auditは短期windowへ縮小し、chart source windowと全chart JSON生成は暫定的に残す。
- **非結論**: このパージだけでscanner高CPUやsnapshot遅延が解決するとは扱わない。chart生成は全rowの
  JSONを毎cycle書き、旧3市場`marketComparison`も別collectorとして残るため、完了後も独立P1で測る。
- **現在地**: CP-01〜06を完了し、実unit同期、runtime継続、CPU/RSS、実画面を確認した。
- **次の実装**: CPU高負荷を数値付きの独立P1で区間計測する。本計画へ最適化を追加しない。
- **最大の実装risk**: Windows `U:` viewでは5つのshell scriptが`100755 → 100644`のmode-only差分に
  見える。内容差分は0行で、`core.fileMode=false`では消える。canonical Linux checkoutで再確認し、
  このmode noiseをstage/commitしない。内容差分が見つかった場合だけ停止する。

## 1. 作業契約

### Objective

74時間前との比較で「数日前から動き始めた銘柄」を探す機能は、現行製品の中心価値である
Bitget × Hyperliquid Core Perp比較に対して費用が大きく、ユーザー価値が限定的である。
その機能を維持するためだけの履歴取得、全量計算、公開field、Candidate説明を削除し、scannerの
production負荷と保守対象を縮小する。

### Target

1. `74h`をproduction timeframe、価格・売買代金feature、Candidate rule、snapshot row/summary、
   reason code、Dashboard/Symbol表示、filter設定から除去する。
2. `userRule74hMatched is True`を前提としたCandidate laneを削除する。Candidate用の
   `rankings.timeframes`、`rankings.meta.timeframes`、ranking API、Symbol上のCandidate順位も削除し、
   別条件でCandidateを再定義しない。
3. 常駐serviceのdeep backfill CLI options、task、進捗state、systemd設定、Web表示を削除する。
4. `service_deep_backfill.py`とそのpure testは未接続の将来用componentとして残してよい。
5. 現行の短期指標に必要な5分足数をコードから導出する。scanner判定とgap auditの対象は383本5分足、
   1,915本1分足、31時間55分とする。
6. detail chartを残す間は、chart sourceだけ現行と同じ1,177本5分足、5,885本1分足、98時間5分を
   読み込む。scannerへは末尾383本だけを渡し、gap auditでchart用全windowをPython object化しない。
7. snapshot schema version 1、Cold snapshot公開、Perp比較sidecar、OI 60分、短期指標、reconcile、
   detail chart、既存DB schemaを維持する。
8. source変更前とruntime qualificationでCPU、RSS、snapshot間隔、row/chart件数を同じ条件で記録する。

### Preserve

- `summary.perpVenueComparison`のfield、取得周期、fail-closed挙動。
- 旧3市場`summary.marketComparison`は今回だけ変更しない。製品方針として存続を承認した扱いにはせず、
  Bitget × Hyperliquid Coreと重複するlegacy pilotとして別計画の削除候補にする。
- Watchlist、Raw Sort、Smart Rank、選択銘柄detail、Hot ticker、VPI-Lite+、OI 60分の意味。
- 5分・15分・1時間・4時間・24時間の価格変化、売買代金、既存の短期量倍率。
- detail chartの現行source深度。短期windowだけへ一律縮小しない。
- `rankings.noTrade`診断。Candidateの代替として広い銘柄群を表示する用途には転用しない。
- snapshot schema version 1、DuckDB schema、既存candle/OIデータ、single writer。
- public market data only、監視専用、注文・残高・position・秘密APIなしの境界。
- 無関係な未コミット変更と、完了済みmultisource実装。

### Non-goals

- Candidateを「市場の動き」などの新機能へ改称して全非`NO_TRADE`銘柄を並べること。
- chart JSON、chart API、`lightweight-charts`、短期candle、reconcileの削除。chart削除は推奨するが、
  user-visible機能とADR/API/packageを変更するため別EXECPLANにする。
- rolling state、incremental snapshot、gap auditのSQL化、DuckDB migration。
- Bitget × Hyperliquid Core比較をWebの唯一のデータモデルにする全面改修。
- 旧3市場`marketComparison`、Bybit、VPI-Lite+、OI 60分の削除。`marketComparison`/Bybitは
  現行製品対象と重複するため、chartと同様に別の削除候補として明記する。
- 現役DBの履歴削除、VACUUM、別writer、private API、売買・裁定判定。
- push、PR、merge、service restart。実施する場合はメインスレッドの現行承認を確認する。

## 2. 事実・推論・未確認事項

### 確認済み事実

| ID | Fact | Evidence |
|---|---|---|
| F-01 | 74時間featureは888本の5分足を参照し、24時間比較用288本と合わせて最低1,177本を要求する | `domain/features/long_horizon.py`、filter config |
| F-02 | service snapshotの1分足読込上限は`max(min_required_bars * 5, max(TIMEFRAME_BARS) * 5)`で、現在5,885本になる | `application/service_snapshot.py` |
| F-03 | Candidate rankingsは非`NO_TRADE`かつ`user_rule_74h_matched is True`のrowだけを対象にする | `domain/screening/rankings.py` |
| F-04 | 74時間ruleはrow field、summary、reason code、filter TOML、Dashboard、Symbol画面、schema/generated typeへ接続されている | source/schemaの`74h`参照 |
| F-05 | systemd unitは`--deep-backfill-limit 5885`で常駐deep backfillを有効化している | `config/systemd/prep-watchdeck-service.service.in` |
| F-06 | deep backfillはservice CLI、runtime task、service state、Web stateへ接続されている | CLI、service publisher/models、Web parser |
| F-07 | detail chartとDashboard/Symbolの短期指標はcandle履歴に依存する | chart publisher、feature modules、Web chart route |
| F-08 | Cold snapshotはWebのDashboard、Symbol、summary、rankings、Perp比較の現行公開境界である | `snapshot-repository.ts`、`docs/current/data-contracts.md` |
| F-09 | 4時間量倍率はbaseline 288 sampleと48本windowを使い、必要5分足は`288 + 2*48 - 1 = 383`本である | `features/volume_ratio.py` |
| F-10 | reconcileは直近既定60本の1分足欠損を対象にし、deep backfillとは責務が異なる | `application/service_reconcile.py` |
| F-11 | detail chartは全snapshot rowについてtemporary JSONを作り、各fileをflush/fsync後に置換する | `application/chart_artifacts.py` |
| F-12 | chartは最大128本を表示するが、入力383本では1h/4h/24hが概ね32〜33本/8〜9本/2〜3本まで減る。現行1,177本では概ね99〜100本/25〜26本/5〜6本である | `TIMEFRAME_BARS`と`chart_timeframes_from_5m()` |
| F-13 | periodic Cold snapshotの既定周期は60秒である | `settings.py` |
| F-14 | 旧`marketComparison`はBitget、Bybit、HyperliquidのBTC/ETH/SOL固定pilotで、`perpVenueComparison`とは別collector・別panelである | market comparison source/Web component |
| F-15 | snapshot rootは`additionalProperties: false`だが、row、summary、rankingsは`additionalProperties: true`である。rowから74時間property定義を削除しても、旧snapshotの追加fieldはschema上許容される | `dto.py`、generated JSON Schema |

### 推論

| ID | Inference | Basis |
|---|---|---|
| I-01 | 74時間計算だけを削除してCandidateを全非`NO_TRADE`へ広げると、同名機能の意味を無断変更する | F-03とUI表記 |
| I-02 | snapshot artifact自体を同時削除するとWebのdata contract再設計が必要になり、今回の負債削除を超える | F-08 |
| I-03 | 74時間削除後も短期指標とchartを残す限りcandle履歴とreconcileはゼロにはできない | F-07、F-09、F-10 |
| I-04 | scanner/gap auditを1,915本へ縮小しても、chart用5,885本1分足からの5分集計と全row JSON書込みが残るため、高CPU・遅延解決は保証できない | F-11〜F-13とsnapshot処理経路 |
| I-05 | 383本へ一律縮小してchartを「維持」とするのは、表示履歴を大幅に減らす未承認の挙動変更である | F-12 |
| I-06 | 旧`marketComparison`は現行のBitget × Hyperliquid Core比較に対して重複と追加network/lifecycleを持つが、CPU寄与は未計測である | F-14 |

### 仮定・未確認事項

| ID | Type | Content | Impact if wrong | Resolution |
|---|---|---|---|---|
| U-01 | confirmed local artifact | Windows viewの5 script差分は`100755 → 100644`だけで、内容差分は0行 | mode-only差分をstageすると実行権限を壊す | canonical Linuxで再確認し、mode changeをstageしない。内容差分があれば停止 |
| U-02 | assumption | 既存runtime DBには短期指標に必要な1,915本相当が既にある | fresh stateまたは履歴不足銘柄はscannerが最大31時間55分warm-upする。chartの現行深度は最大98時間5分を要する | DBは削除せず、qualificationでcoverageを測る。自動seedは別計画 |
| U-03 | unknown | 74時間削除後の実CPU、RSS、snapshot時間 | 期待した負荷改善が出ない可能性 | CP-06で実測し、P1 performance計画へ渡す |
| U-04 | assumption | Candidate lane削除後もWatchlistを主導線として利用できる | Dashboardの探索性が不足する可能性 | responsive E2Eと実画面で確認。新探索機能は本計画へ追加しない |
| U-05 | unknown | detail chartと旧3市場panelの実利用価値 | 削除判断をsunk costまたは推測だけで行う危険がある | 今回は維持し、削除候補として別計画で判断する |

## 3. 選択肢比較

| Option | 内容 | 利点 | 欠点 | 判断 |
|---|---|---|---|---|
| A | 現状維持 | 変更リスクなし | 5,885本deep backfill、74時間依存、全量計算を維持 | 不採用 |
| B | 74時間と常駐deep backfillをパージし、scanner/gap audit windowだけ383本へ分離する | 目的に直結し、短期指標と現行chart深度を維持 | chart用5,885本読込と全量JSON生成は残る | **今回採用** |
| C | chartを残したままsnapshot全windowを383本へ縮小 | 実装が最も単純で読込量も減る | 1h/4h/24h chart履歴が大幅に減り「維持」と矛盾 | 不採用 |
| D | chartを削除して全windowを383本へ縮小 | Perp比較中心の製品に合い、I/Oと依存を大きく減らす | user-visible機能、API、ADR、packageへ波及 | **推奨する別EXECPLAN** |
| E | Perp会場比較専用へ全面転換し、scanner candle stackを削除 | 最も単純で負荷削減が大きい | Watchlist、短期指標、chart、VPI、reconcileなど広範囲を失う | 別EXECPLAN |

## 4. Acceptance criteria

| ID | Mandatory | Condition | Verification | Status | Evidence |
|---|---:|---|---|---|---|
| AC-01 | yes | 新producer、schemaの明示property、generated typeの明示property、active config、fixture、現行UIに74時間rule/field/timeframeが残らない。旧snapshotの追加field許容は互換性のため維持する | scoped `rg`、schema generation、focused tests | passed | CP-03 schema/type再生成、focused pytest 61件、旧追加field互換test、production scoped `rg` 0件 |
| AC-02 | yes | Candidateは別条件へ広げず、Candidate固有ranking data/API/UI、Symbol順位、rule説明を削除する | ranking unit、Vitest、E2E、final diff | passed | CP-02 Web unit 60件、Svelte check/build、関連Playwright 55件、scoped `rg`成功 |
| AC-03 | yes | `rankings.noTrade`、Watchlist、Raw Sort、Smart Rank、5m/15m/1h/4h/24h表示を維持する | focused Python/Web/E2E | passed | CP-02 Playwright 55件とCP-03 ranking/provider/fixture testsで維持を確認 |
| AC-04 | yes | production serviceにdeep backfill flag/task/state/systemd/Web接続がない | CLI help、service tests、unit template、Web parser tests、`rg` | passed | CP-01 focused gate 35 pytest、5 Vitest、1 Bun test、Svelte check。production entrypoint/state接続0件で、独立component/model/testだけが残存 |
| AC-05 | yes | `service_deep_backfill.py`とpure testはproduction entrypointから未参照の独立部品として残る | import graph `rg`、focused test | passed | component importは`test_service_deep_backfill.py`だけ。pure test 3件成功 |
| AC-06 | yes | scanner判定とgap auditは383本5m/1,915本1mから導出し、chart sourceは現行1,177本5m/5,885本1mを維持する。一つのwindowを兼用しない | pure/config/snapshot/chart tests | passed | CP-04 focused pytest 59件でrow tail 383、gap inclusive 1,915、chart source 1,177/5,885を確認 |
| AC-07 | yes | Cold snapshot、Perp comparison、OI 60m、reconcile、chart、DB schema、schemaVersion 1を維持し、featureVersion 5/rulesetVersion 4を公開する | snapshot tests、schema diff、final diff | passed | scanner 253件、Web 224件、E2E 64件、schema/type diff reviewで維持を確認 |
| AC-08 | yes | current docs、ADR 0008、active P1 planを実装後の事実へ同期し、歴史的判断を捏造せずsupersedeする | docs checker、link checker、diff review | passed | CP-05 docs同期、新ADR 0010、ADR 0007/0008と旧P1 planのanti-resumeを反映。metadata test 13件、link test 4件、両checker、DESIGN lint、diff-check成功 |
| AC-09 | yes | focused tests、Ruff、Pyrefly、Web unit/check/build、関連E2E、`verify-local.sh`、`git diff --check`が成功する | command exit 0 | passed | `verify-local.sh` exit 0。maintenance 82、scanner 253、Web 224、E2E 64件、Ruff/format/Pyrefly/check/build成功 |
| AC-10 | yes | runtimeでsingle DuckDB writer、fresh snapshot 3回、既存Bitget scanとPerp比較継続、restart loopなしを確認する | isolated/live qualification | passed | writer PID 3867036だけ。最初の3 snapshotはPerp各161 ready、OI reference 744/739/737。後続2周期のticker鮮度切れではOIがfail-closedでUNKNOWNとなり、その後2周期で744/742 referencesへ自動回復。両unit active/running・NRestarts 0、Web health OK |
| AC-11 | yes | source変更前後で同じpidstatコマンドを使い、CPU、RSS、snapshot間隔、row/chart件数と測定時の処理状態を記録する。cycle位相を揃えられない値から因果を断定せず、負荷問題が残れば独立P1へ分離する | before/after measurement | passed | 20秒sampleはCPU 78.95%→93.25%、RSS 2,512,282→572,110 KiB、公開間隔194.810/220.894→105.225/126.055秒。変更後はreconcile実行中で、CPUの悪化・改善は判定不能。独立P1作成 |

## 5. Checkpoints

### CP-00: Worktreeとbaselineの安全確認

- **Status**: completed
- **Goal**: 既存変更を失わず、現行Perp比較を含む正しいbaselineから専用branchを作る。
- **Linked ACs**: 全ACの前提。
- **Dependencies**: なし。
- **Targets**: Git状態、既存active plans、`.codex/SP_STATE.md`。
- **Work**:
  1. canonical checkout `/home/tn/projects/prep-watchdeck`でbranch、HEAD、status、diffを再確認する。
  2. `ad3364f`以後に変更がある場合は現行HEADへ本計画を再同期する。
  3. Windows viewの5 script差分がmode-onlyであることを`git diff --raw/--summary/--numstat`と
     `git -c core.fileMode=false status --short`で確認する。canonical Linuxで内容差分が出た場合だけ停止する。
  4. source変更前の連続3 snapshot cycleについて、取得可能なCPU、RSS、snapshot間隔、row数、chart
     file数を記録する。processやlogから取れない値を推定しない。
  5. current Perp比較HEADから`ai/purge-74h-deep-backfill-YYYYMMDD-HHMM`を作る。
- **Completion criteria**: baseline、branch、dirty fileの扱い、変更前計測または取得不能理由がplanへ記録され、
  対象外差分が保護されている。
- **Verification**: `git status --short`、`git diff -- <dirty paths>`、`git log -5 --oneline`。
- **Stop**: canonical Linuxでscript内容差分が見つかり、今回変更または検証と衝突する。
- **Recovery**: 編集せず停止し、内容差分の所有者または扱いだけを確認する。mode-only noiseでは停止しない。

### CP-01: 常駐deep backfillをproductionから切断

- **Status**: completed
- **Goal**: 5,885本deep backfillがservice起動、状態公開、systemdから実行されないようにする。
- **Linked ACs**: AC-04、AC-05、AC-07。
- **Dependencies**: CP-00。
- **Targets**:
  - `apps/scanner-core/src/prep_watchdeck/interfaces/cli.py`
  - `apps/scanner-core/src/prep_watchdeck/application/service_publisher.py`
  - `apps/scanner-core/src/prep_watchdeck/domain/service_models.py`
  - `apps/scanner-core/tests/test_service_runtime.py`
  - `apps/scanner-core/tests/test_service_state.py`
  - `apps/scanner-core/tests/test_service_deep_backfill.py`
  - `apps/web/src/lib/service-state.ts`
  - `apps/web/src/lib/service-state.test.ts`
  - `config/systemd/prep-watchdeck-service.service.in`
  - `scripts/ops/install-user-services.test.mjs`
- **Work**: deep backfill options、tracker/provider/task、cancel/await、state field、Web優先表示、unit引数を
  削除する。`service_deep_backfill.py`と`test_service_deep_backfill.py`は未接続部品として残す。
- **Preserve**: standard backfill、直近reconcile、watchdog、snapshot、ticker、Perp refresh。
- **Completion criteria**: production entrypointからdeep backfill参照がなく、direct component testだけが残る。
- **Verification**: CLI/service/state/Web/systemd focused tests、scoped `rg`。
- **Failure modes**: shutdown task list漏れ、古いservice-state reader破損、systemd template test不一致。
- **Rollback**: checkpoint単位のcommitをrevertする。DB rollback不要。

### CP-02: Candidate consumerと74時間UIを先に切断

- **Status**: completed
- **Goal**: 74時間gateのない値をCandidateとして表示せず、Watchlist主導線を維持する。
- **Linked ACs**: AC-01、AC-02、AC-03、AC-07。
- **Dependencies**: CP-01。
- **Targets**: `DashboardRankingArea.svelte`と`DashboardRankingPanel.svelte`、Dashboard route、candidate
  rule formatter、ranking parser/API/repository、Symbol Monitoring RailのCandidate順位、74時間
  labels/filter/sort、Selected/Symbol market context、Symbol timeframe route、関連Vitest/E2E。
- **Work**:
  1. `DashboardRankingArea`とCandidate rule説明を削除する。
  2. Candidate ranking API/repository/parserとSymbol Monitoring RailのCandidate順位表示を削除する。
  3. Candidate slot内の非Candidate panelは新しい意味を付加せず、既存順序でcontext領域へ移す。
  4. Watchlist、Selected detail、Smart Rank、market/VPI panelsのkeyboard到達性を維持する。
  5. 全timeframe selectorと表示から`74h`だけを削除する。
  6. `candidate`を単なるローカル変数名として使うparserコードは意味が異なるため機械的に削除しない。
- **Completion criteria**: 画面にCandidate/74時間ruleがなく、広い銘柄群をCandidateとして表示しない。
- **Verification**: parser/component tests、Svelte check/build、1440px/390px E2E。
- **Failure modes**: layout空白、focus順退行、market/VPI panel消失、persisted 74h settingで例外。
- **Recovery**: CP-02 commitをrevert。backendはまだ旧fieldを生成しているため独立して戻せる。

### CP-03: Scannerの74時間producer・公開契約をパージ

- **Status**: completed
- **Goal**: consumer切断後に、74時間計算と設定・row/summary/reason/schemaを除去する。
- **Linked ACs**: AC-01、AC-03、AC-06、AC-07。
- **Dependencies**: CP-02。
- **Targets**: `long_horizon.py`、constants/models/config、pipeline/provider/fixture、DTO、rankings、
  3 filter TOML、snapshot schema/generated type、関連Python/Web tests/fixture。
- **Work**:
  1. 最小REDで、74時間field/timeframeが出力されず短期fieldが残る契約を固定する。
  2. `UserRuleConfig`、74時間feature、row field、summary、reason code、`candidate_rule_counts`を削除する。
  3. ranking outputはrequired `rankings` objectと`noTrade`を維持し、Candidate用`timeframes`と
     `meta.timeframes`は出力しない。空のCandidate treeも生成しない。
  4. schemaをPydanticから再生成し、generated TypeScriptを手編集しない。
  5. `featureVersion`を`5`、`rulesetVersion`を`4`へ更新する。schemaVersionは`1`を維持する。
  6. 新producerは74時間fieldを出力しない一方、`additionalProperties: true`のrow/summary/rankingsにより
     保存済み旧snapshotをreaderが拒否しない回帰testを追加する。
- **Preserve**: OI field、activity phase、短期volume ratio、Perp sidecars。
- **Completion criteria**: production/config/schema/fixtureのscoped `rg`で74時間参照が0件。
  ADR/過去planの歴史的記録と、互換性test内のlegacy fixtureは対象外。
- **Verification**: domain/config/provider/ranking/snapshot focused pytest、schema generation、Web unit/check/build。
- **Stop**: 74時間field削除にDB migrationが必要になる、またはPerp sidecarへ波及する。
- **Rollback**: CP-03 commitをrevert。保存済み旧snapshotはreaderが拒否せず、次cycleで置換する。

### CP-04: scanner/gap audit windowをchart source windowから分離

- **Status**: completed
- **Goal**: scanner判定とgap auditから74時間用windowを外す一方、今回維持するdetail chartのsource深度を
  暗黙に縮めない。
- **Linked ACs**: AC-06、AC-07。
- **Dependencies**: CP-03。
- **Targets**: filter config/TOML、volume ratio、service snapshotのanalysis/chart/gap window計算、
  chart artifact、focused tests、operations docs。
- **Work**:
  1. 必要5分足を`baseline_sample_count + 2 * max_active_window - 1`から導出する。
  2. scanner analysis/gap auditは383本5分足、1,915本1分足になることをpure testで固定する。
  3. chart sourceは暫定的に現行1,177本5分足、5,885本1分足を明示し、scanner row計算へは
     symbolごとの末尾383本だけを渡す。
  4. gap auditは1,915本windowだけを読み、chart用98時間5分の1分足を全銘柄Python objectとして
     読み込まない。
  5. chart payloadの1h/4h/24h本数が変更前fixtureより減っていないことを固定する。
  6. fresh state自動seedを常駐serviceへ追加しない。履歴不足は`MISSING`としてfail-closedにする。
- **Preserve**: reconcileの直近60本、chart source深度、VPI target用1分足、既存DB rows。
- **Completion criteria**: scanner/gap auditは1,915本、chart sourceは5,885本として別々に動き、短期指標と
  chart depthのfocused testが通る。
- **Stop**: 一つのwindowへ戻す必要がある、chart深度が減る、またはAPI/指標計算上383本で不足する。
- **Residual risk**: fresh stateでscannerは最大31時間55分、現行chart深度は最大98時間5分warm-upする。
  chart用5,885本1分足からの5分集計と全row JSON書込みは残るため、CPU問題解決とは扱わない。

### CP-05: 文書・設計判断・最終local gate

- **Status**: completed
- **Goal**: 実装と現行文書を同期し、歴史的記録と現行仕様を区別する。
- **Linked ACs**: AC-08、AC-09。
- **Dependencies**: CP-01〜04。
- **Targets**: README、`DESIGN.md`、docs/current、`config/scanner-filters/README.md`、新ADR、
  ADR 0007/0008のsupersession表記、active P1 plan、本plan、runbook、`.codex/SP_STATE.md`、validation。
- **Work**:
  1. `docs/current`から74時間/deep backfill現行記述を削除する。
  2. 新ADR 0010を追加し、74時間Candidateと常駐deep backfillのretirement、snapshot/short
     candle/reconcile/chart維持、window分離を記録する。
  3. ADR 0007/0008は削除せず、0010によりCandidate/74時間部分がsupersededになったことを追記する。
     ADR 0008のOI 60分契約は維持する。
  4. `DESIGN.md`からCandidate前提のinformation architecture、responsive、VPI配置を実装後の構造へ
     更新し、design lintを実行する。
  5. `p1-candidate-oi-contract`は実装履歴としてarchive待ちまたはsupersededに更新する。
  6. runbookとexecution stateをCP-06の実unit同期手順まで更新する。
  7. focused gate後、`bash scripts/verify-local.sh`を1回実行する。
- **Completion criteria**: mandatory local testがexit 0、docs/check links/diffがclean、scope外差分なし。
- **Stop**: unrelated existing test failureを回帰と分離できない。未実行・skippedを成功扱いしない。

### CP-06: runtime qualificationとP1計測

- **Status**: completed
- **Goal**: パージ後の稼働継続と実負荷を確認し、performance改善を捏造しない。
- **Linked ACs**: AC-10、AC-11。
- **Dependencies**: CP-05、メインスレッドでのrestart承認。
- **Targets**: resolved state root、systemd unit、snapshot/service state、実画面。source変更は原則なし。
- **Work**:
  1. `systemctl --user cat`とinstaller `--check`で実unitの旧deep引数driftを確認する。
  2. installer dry-runで差分が旧deep引数除去だけと確認してから`--apply`し、再`--check`を通す。
  3. restart前後のMainPID、ActiveState、SubState、NRestarts、single writerを記録し、各unitを1回だけ
     restartする。
  4. fresh snapshotを3回確認し、Bitget rows、Perp sidecar、OI/reconcile、Web healthを確認する。
  5. 1440px/390pxでCandidate非表示、Watchlist/Selected detail/Perp比較を確認する。
  6. CP-00と同じ方法でscanner CPU、RSS、snapshot間隔、chart file数、row数を記録する。
- **Completion criteria**: runtime回帰なし。取得できた変更前後の数値と、取得不能項目を区別して残す。
  performance改善率は本計画のPASS条件にせず、別P1の入力にする。
- **Stop**: snapshot停止、restart loop、Bitget scan退行、Perp比較消失、複数writer。
- **Recovery**: checkpoint commitsを逆順にrevertし、同じunitを承認範囲内で1回再起動する。

## 6. 実装後に別判断する事項

### D-01: detail chartを削除するか

chartはPerp会場比較には不要で、全snapshot rowについて毎cycle JSONをflush/fsyncする負荷を持つ。
現行のSymbol分析機能でもあるため本計画中には削除しないが、サンクコストではなく製品対象との整合と
実測負荷から、次の削除候補として優先する。削除する場合はchart artifact publisher、API route、
repository、component、E2E、`lightweight-charts`、ADR 0004を一つの別EXECPLANで扱う。

### D-02: 比較専用アプリへ全面転換するか

`perpVenueComparison`を主データにし、short candle、reconcile、gap audit、VPI、scanner rowを削除すれば、
負荷と構造は大幅に単純化できる。ただし既存の短期監視機能を失うため、別EXECPLANと明示承認が必要。

### D-03: fresh stateの短期履歴をどうseedするか

短期指標を維持し、31時間55分のscanner warm-upを許容できない場合だけ、停止中に実行する明示的な
one-shot maintenance commandを設計する。chartを維持する場合の現行深度warm-upは98時間5分である。
常駐deep backfillの復活や現役DBへの別writer接続は行わない。

### D-04: 旧3市場`marketComparison`を削除するか

旧pilotはBTC/ETH/SOLのBitget・Bybit・Hyperliquid median panelで、現行対象のBitget × Hyperliquid Core
`perpVenueComparison`と役割が重複する。Bybitは現行の対象ユーザー・会場に含まれない。
network取得とservice lifecycleは追加しているがCPU寄与は未計測である。今回の74時間パージへ混ぜず、
chart判断と同じ次段で、panel、collector、Bybit adapter、tests、docsを削除候補として評価する。

## 7. Progress / decisions / evidence

- 2026-08-12 — userが74時間判定の明確なパージを指示した。
- 2026-08-12 — deep backfillは常駐mainから外し、必要なら未接続の将来部品だけ残す方針を確定した。
- 2026-08-12 — snapshot/chart/candle/reconcileを分解し、snapshotは公開境界として維持、chartは別判断、
  reconcileは短期candleを残す間維持する方針を確定した。
- 2026-08-12 — current codeから74時間、Candidate gate、deep backfill、snapshot、chart、短期windowの
  依存をread-onlyで確認した。
- 2026-08-12 — 本plan、runbook、handoff、最初の`.codex/SP_STATE.md`を作成。実装は未着手。
- 2026-08-12 — plan reviewで383本windowと現行chart深度の非両立を確認した。scanner/gap auditの
  1,915本windowとchart sourceの5,885本windowを分離し、chartと旧`marketComparison`を次段の
  優先削除候補として明記した。
- 2026-08-12 — CP-00完了。canonical Linuxでbranch
  `ai/multisource-display-pilot-20260811-1948`、HEAD `ad3364f6e3b0c30c85469a22da3789f19d3727b9`、
  origin一致を再確認した。5本のscriptはcanonical Linuxでは内容・modeとも差分なし。既存の
  `docs/README.md`と本plan directoryだけが未コミットであり、保持したまま
  `ai/purge-74h-deep-backfill-20260812-2004`を作成した。
- 2026-08-12 — CP-00変更前計測。同一worker PID `981456`で`pidstat -r -u -p 981456 1 20`を実行し、
  CPU平均`78.95%`、RSS平均`2,512,282 KiB`を観測した。point sampleではRSSが最大
  `4,964,240 KiB`まで増えた。連続3 snapshotの`generatedAt`は
  `2026-08-12T10:57:42.973Z`、`2026-08-12T11:00:57.783Z`、
  `2026-08-12T11:04:38.677Z`で、公開間隔は`194.810秒`、`220.894秒`。row/chart件数は
  `329/329`、`329/329`、`327/327`、Perp itemは各`161`だった。これはsnapshot公開間隔であり、
  build durationではない。
- 2026-08-12 — CP-01完了。productionのCLI option、runtime task/provider/shutdown、service state、Web表示、
  systemd引数からdeep backfillを切断した。`service_deep_backfill.py`、`DeepBackfillProgress`、pure test 3件、
  既存DB candleは維持した。指定focused gateはscanner pytest 35件、Ruff、Web Vitest 5件、
  Svelte check、systemd installer test 1件が成功。production scoped `rg`は接続0件、`git diff --check`成功。
- 2026-08-12 — CP-02完了。Candidate UI/API/parser/repository、SymbolのCandidate順位、74時間selector・
  表示を削除し、Market comparison/VPIを任意context領域へ移した。Watchlist、Selected detail、Smart Rank、
  Perp比較は維持。focused Web unit 60件、Svelte check、build、関連Playwright 55件が成功し、
  production Web sourceのCandidate固有/74時間参照はlegacy互換testとCP-03までのreason遮断を除き0件。
- 2026-08-12 — CP-03完了。74時間feature/config/row/summary/reason/schemaとCandidate ranking producerを
  削除し、`featureVersion=5`、`rulesetVersion=4`へ更新した。`schemaVersion=1`、`rankings.noTrade`、
  短期指標、OI、Perp sidecar、旧snapshot追加property読込互換は維持した。focused scanner pytest 61件、
  Ruff、format、Pyrefly、schema/type生成、Web unit 224件、Svelte check、build、scoped `rg`、
  `git diff --check`が成功した。
- 2026-08-12 — CP-04完了。active configを導出式どおり383本へ変更し、不一致を拒否する。serviceは
  scanner rowへ末尾383本、gap auditへinclusive 1,915本だけを渡し、detail chartと
  `serviceCandles1m`は明示した1,177本5分足/5,885本1分足sourceを維持する。focused pytest 59件、
  Ruff、format 141 files、Pyrefly 0 errors、`git diff --check`が成功。chart全銘柄生成負荷は残る。
- 2026-08-12 — CP-05文書同期とfocused gate完了。README、DESIGN、docs index/current、filter READMEを
  現行codeへ同期し、ADR 0010を追加、ADR 0007/0008と旧P1 planへsupersession/anti-resumeを記録した。
  metadata test 13件、link test 4件、両checker、DESIGN lint（error/warning 0）、`git diff --check`が成功。
  このfocused gate時点では`verify-local.sh`未実行。後述のCP-05全体gateで1回実行した。
- 2026-08-12 — CP-06 runbookを実unit driftへ同期。restart前に`systemctl --user cat`、installer
  `--check`、dry-run限定差分確認、`--apply`、再`--check`を行い、旧deep引数以外のdriftではrestartせず
  停止する。unit同期後にscanner/Webを各1回だけrestartする。
- 2026-08-12 — CP-05全体gate完了。最初の隔離試行はuser namespaceの権限差により既存permission testが
  無効化され、正式gateとして採用しなかった。有効な権限での実行は既存fixture testの
  `baseline_window_bars=96`と導出`min_required_bars=289`の不整合を検出したためtest fixtureを1行修正。
  修正後の`bash scripts/verify-local.sh`はexit 0で、maintenance 82件、scanner 253件、Web 224件、
  Playwright 64件、Ruff、format、Pyrefly、Svelte check、buildがすべて成功した。
- 2026-08-12 — CP-06完了。installer dry-runで実unit driftが旧deep引数除去だけと確認し、backupを
  作成してapply、再check成功後にscanner/Webを各1回restartした。MainPIDは`3867000`/`3867001`、
  双方`active/running`、`NRestarts=0`。DuckDB writerはworker `3867036`だけだった。
- 2026-08-12 — restart直後のfresh snapshotは`20260812T132007Z`、`20260812T132152Z`、
  `20260812T132358Z`の3回で、間隔105.225秒/126.055秒、row/chartは337/337、336/336、336/336、
  Perpは各161 ready、OI referenceは744/739/737、その時点のreconcileはerror 0で進行した。Web healthはOK。
- 2026-08-12 — 同じpidstatコマンドによる20秒sampleはCPU平均78.95%→93.25%、RSS平均
  2,512,282→572,110 KiB。変更後sampleはreconcile実行中でcycle位相を揃えていないため、CPUの悪化・改善や
  パージとの因果は判定不能。CPU高負荷は未解決で、`scanner-cpu-snapshot-latency-p1`へ区間計測を分離した。
- 2026-08-12 — Playwright CLIで1440x1000/390x844の実サービスを確認。AAVEのBitget/Hyperliquid
  2/2、Mark price、Funding、建玉、24h出来高、USDT/USDCを表示し、Candidate/74h文言とconsole errorは0。
  screenshotはstate rootの`tmp/purge-74h-qualification/desktop-1440.png`と`mobile-390.png`。
- 2026-08-12 — Bitget public ticker refreshは22:27:15と22:33:31 JSTに2回失敗した。後続snapshot
  `20260812T133313Z`と`20260812T133748Z`はtickerの2分鮮度条件によりOIを再利用せず、
  `sampled=0 / references=0`、全336行`UNKNOWN`としてfail-closedで公開した。処理例外ではないため
  `oiDiagnostics.status`は`ok`のままであり、これは監視上の残リスクである。
- 2026-08-12 — ticker更新後、`20260812T134135Z`はOI `746/744`、`20260812T134446Z`は`744/742`へ
  無介入で2周期連続回復した。ticker runtimeはsequence 10、full updates 753件、delta updates 746件まで
  進み、22:41以降に同warningは追加されていない。purge差分はOI採取・ticker refresh経路を変更していない。
  原因は一時的なBitget ticker更新失敗との強い相関まで確認したが、例外詳細は現在のlogから未確認である。
- 2026-08-12 — 後続`20260812T134847Z`はcurrent OIを744件sampleしたが、exact 60分前bucketがなく
  references 0、333行すべて`UNKNOWN`になった。次の`20260812T135233Z`は744/742へ戻った。これは
  nearest値へfallbackせず欠損を`UNKNOWN`にする既存契約と一致する一方、OI状態の連続可用性は保証しない。
- 2026-08-12 — reconcileは継続し、後続確認時点ではBitget timeout 2件（latest `CAPUSDT`）を記録した。
  serviceは`active/running`、`NRestarts=0`でsnapshot更新も継続しており、今回のパージ回帰とは判定しない。
- 2026-08-12 — 上記の後続runtime事実へ文書を同期し、metadata test 13件、link test 4件、両checker、
  `git diff --check`を再実行して成功した。sourceを変更していないためfull gateは繰り返していない。

## 8. Final result

- **Result**: PASS
- **Actual state**: CP-00〜06完了。専用branchと変更前計測を確定し、productionの常駐deep backfill接続、
  Candidate consumer、74時間producer・公開契約をsource/config/schemaから除去し、analysis/gapとchart
  source windowを分離した。文書・full gate・unit同期・runtime・実画面まで確認済み。
- **Goal gap**: mandatory gapはなし。CPU高負荷の原因特定と、current sample鮮度切れ・exact reference欠損の
  どちらでもOIが全件`UNKNOWN`かつdiagnosticsが`ok`になり得る監視盲点は残るが、本計画のパージ範囲外である。
- **Resume requirement**: 本計画の再実行は不要。次は独立P1の区間計測から開始し、ticker最終成功時刻と
  OI sampled/reference数も同じ時系列へ記録する。
