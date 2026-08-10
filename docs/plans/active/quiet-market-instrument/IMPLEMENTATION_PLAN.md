# Quiet Market Instrument 実装計画

- 作成: `2026-08-10T19:45:00+09:00`
- 更新: `2026-08-10T22:35:24+09:00`
- 検証: `2026-08-10T22:35:24+09:00`
- 状態: `実装計画`

## 0. 最終状態

- Plan ID: `PLAN-QUIET-MARKET-INSTRUMENT-001`
- Revision: `4`
- Profile / risk: `EXECPLAN / MEDIUM`
- Branch: `ai/quiet-market-plan-sync-20260810-2232`
- Parent HEAD: `8a17b68cf2c8283a7c89cf51b7c2539c11d9358e`
- Implementation commits: `aeb0d9cebd314c6e7b44e01fc42a5386bda0a7a1`、`046c9aff3712111ad09084cae179b599edb06452`
- Main merge: `ce719dd10a59b0f548d4cf649bf125e11cc80c40`（PR #3）
- Final HEAD: `このplanを最終同期するlocal commit自身`
- Verified tree: commit後の`HEAD^{tree}`。自己参照を避けるため正確なhashは`.ai-work/state.md`と最終報告へ記録する。
- Current checkpoint: `complete`
- Result: `PASS`

## 1. 実装結果

監視専用境界、Candidate/OI algorithm、Watchlist、Raw Sort、Smart Rank計算、VPI-Lite+、Cold/Hot、Chart、Past Note、Dashboard設定、data-quality状態を維持した。

- Live/Fixtureの`summary.volumeRatio15m`へactive config由来のrolling 15分基準metadataを追加した。計算、`schemaVersion=1`、generated schema typeは変更していない。
- Desktop Candidateは連続4列、MobileはCSS breakpointで切り替えるautomatic activation tabsとした。`MediaQuery`によるSSR markup分岐はない。
- Watchlist分類、有限値の`×`表記、valid baseline説明、invalid fallback、15mだけのSymbol量倍率行を実装した。
- user-visible `Smart Rank`を`補正順位`へ変更し、`Raw #n → 補正 #n`を最終表示indexから出した。`smart-rank.ts`は無変更である。
- Selected detailを連続Inspectorへ軽量化し、VPI state主・補助値副、OI availability、全signal/risk/reasonを維持した。
- Dashboard/Symbolの24h rangeはdecorative gradientを廃止しneutral trackとmarkerにした。selected/focus/state insetは維持した。
- 追加の用語レビューを反映し、ユーザーが最初に見る表記を`15分量倍率`、`直近約24h中央値比`、`市場活動`へ統一した。`VPI-Lite+`は小さな技術名として残し、stateは従来どおり`活動増加`等の日本語を主表示する。内部enum、payload、計算、ランキングは変更していない。

## 2. Acceptance criteria

| ID | Status | Reproducible evidence |
| --- | --- | --- |
| AC-UI-001 | PASS | `git diff -- apps/web/src/lib/market/smart-rank.ts apps/scanner-core/src/prep_watchdeck/domain/screening/rankings.py`は空。focused E2E 58 PASS。 |
| AC-UI-002 | PASS | `DashboardRankingArea.svelte`のDesktop 4列。final `dashboard-1440.png`。 |
| AC-UI-003 | PASS | 560/390/320px final screenshotsとresponsive E2E。 |
| AC-UI-004 | PASS | `mobile candidate tabs use automatic roving activation` PASS。Arrow、Home、End、wrap、ARIAを検証。 |
| AC-UI-005 | PASS | `categoryCompactLabel` unitとhome E2E。全rowのlabel領域に分類を表示。 |
| AC-UI-006 | PASS | scanner metadata tests 19 PASS、Web helper 9 PASS。valid時は`15分量倍率`と`直近約24h中央値比`、invalid時は期間を推測しないfallbackをhome E2Eで確認。 |
| AC-UI-007 | PASS | symbol-workspace E2EでTimeframe Boardの`em`が1件かつ`15分量倍率`と確認。 |
| AC-UI-008 | PASS | smart-rank E2E PASS、`smart-rank.ts`無変更、Raw→補正表示確認。 |
| AC-UI-009 | PASS | final desktop/mobile visual review、home/symbol workspace E2E。market fact削除なし。 |
| AC-UI-010 | PASS | user-visible名称は`市場活動`、`VPI-Lite+`は小さな技術名。state主・補助値副、OI availability assertion、Cold非再計算E2E PASS。 |
| AC-UI-011 | PASS | full gateのSTALE/PARTIAL/Past Note/Hot/Cold tests PASS。sentinel hash不変。 |
| AC-UI-012 | PASS | 1440/1200/960/560/390/320px visual reviewとresponsive overflow E2E PASS。 |
| AC-UI-013 | PASS | package/lock diffなし。新production dependency 0。 |
| AC-UI-014 | PASS | scanner 19、Web unit 19、check/build、指定focused E2E 58 PASS。 |
| AC-UI-015 | PASS | `bash scripts/verify-local.sh` exit 0: pytest 236、Web unit 183、E2E 59。 |
| AC-UI-016 | PASS | baseline/final比較と3銘柄選択実測。未解決P0/P1なし。 |
| AC-UI-017 | PASS | `DESIGN.md`、current docs、index、config READMEを同期。metadata/link tests 17 PASS。 |
| AC-UI-018 | PASS | 対象source/tests/docsだけを`aeb0d9c`と`046c9af`へcommitし、各commit後cleanを確認。両commitはPR #3経由でmainへmerge済み。 |

## 3. Checkpoints

CP-001〜CP-013はすべて完了。CP-002はPython RED 4件から19 PASS、Web helperはmissing module REDからunit PASS。Wave 1はscanner 19、Web unit 26、check/build、E2E 47 PASS後にWave 2へ進んだ。Wave 2とvisual QA、docs、full gate、final auditを完了した。

用語follow-upは既存checkpointの契約を変えない局所変更として処理した。copy expectationを先にRED化し、helper/component/docsだけを変更した。Smart Rankの計算、VPI payload/enum、Candidate/OI、schema、依存関係は無変更である。

## 4. 実行証拠

- cwd `/home/tn/projects/prep-watchdeck/apps/scanner-core`: focused pytest、exit 0、`19 passed`。
- cwd `/home/tn/projects/prep-watchdeck/apps/web`: specified unit、exit 0、`19 passed`; `bun run check` 0; `bun run build` 0; focused E2E `58 passed`。
- cwd `/home/tn/projects/prep-watchdeck`: `bash scripts/verify-local.sh`、exit 0、pytest 236 / Web unit 183 / E2E 59。
- 用語follow-up focused、cwd `/home/tn/projects/prep-watchdeck/apps/web`: relevant unit `22 passed`、`bun run check` 0、`bun run build` 0、focused E2E `55 passed`。
- 用語follow-up後full gate、cwd `/home/tn/projects/prep-watchdeck`: `bash scripts/verify-local.sh`、exit 0、pytest 236 / Web unit 183 / E2E 59。
- DesignMD 0.1.0: 後続PR #4で既存debtを解消。現行main `8a17b68`でexit 0、errors 0 / warnings 0 / infos 1。
- Visual: resolved state rootの`tmp/quiet-market-instrument/{baseline,final}`。6 viewport、390pxの4 tab、補正順位、3銘柄選択evidenceを保存。
- Sentinel: Past Note `2240c8ad...b24001`、Dashboard設定 `e1e57eb1...4fb7e`で前後一致。
- Final read-only audit: `git diff --check` 0、package/lock diff空、runtime/test artifact・secret・private/trading API・debug logなし。
- GitHub: PR #3 required `verify` PASS、未解決thread 0、merge commit `ce719dd`。実装AI branchはmerge/ancestor確認後にlocal/remoteから削除済み。
- Runtime: 正式user systemdでservice/Webをcontrolled restart。service PID `473720→2008044`、Web PID `3667390→2009307`、両方active/running・NRestarts 0。`dataAsOf 1786365000000→1786365300000`、schema 1、feature/ruleset 3、writer 1、旧process 0、health/UI smoke/sentinel PASS。
- 最終living plan同期後gate、cwd `/home/tn/projects/prep-watchdeck`: `bash scripts/verify-local.sh`、exit 0、pytest 236 / Web unit 183 / E2E 59、lint/type/check/build PASS。

## 5. 差異と判断

- `baseline_window_bars`は5分足本数ではなくrolling 15分値のsample数なので、外部metadataを`baselineSampleCount`とした。
- 実装時点では既存DesignMD failureをbaselineとの差分0で分離した。後続PR #4でunsupported overlay tokenとunused primaryを修正し、現行mainではlint debt 0である。
- P1 planは既存Archive手順がactive planを除外するため削除せず、indexだけ完了済み・Archive待ちへ直した。
- selected/focus/stateのinset lineとmarker outlineはsemantic stateなので削除対象外とした。
- `VPI-Lite+`は内部契約名として削除せず、主要見出しを意味ベースの`市場活動`、技術名を小さな副表示とした。
- metadata helperの精密なtooltipは維持し、短いbaseline labelだけを`直近約24h中央値比`へ変更した。metadata不正時は引き続き期間を推測しない。

## 6. 残余リスクと残作業

- 未解決P0/P1: なし。
- 非blocking残余: なし。
- production service/Webは実装merge後の明示依頼によりcontrolled restart・smoke確認済み。
- screenshots、Playwright output、runtime state、`.ai-work/`はRepo外またはignoredでcommitしない。
- Remaining work: なし。
