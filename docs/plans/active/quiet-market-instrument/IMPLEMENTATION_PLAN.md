# Quiet Market Instrument 実装計画

- 作成: `2026-08-10T19:45:00+09:00`
- 更新: `2026-08-10T20:13:39+09:00`
- 検証: `2026-08-10T20:13:39+09:00`
- 状態: `実装計画`

## 0. 最終状態

- Plan ID: `PLAN-QUIET-MARKET-INSTRUMENT-001`
- Revision: `2`
- Profile / risk: `EXECPLAN / MEDIUM`
- Branch: `ai/quiet-market-instrument-20260810-1943`
- Parent HEAD: `2b5bfd5811bd1bbace829baa365fff332aaa2c46`
- Final HEAD: `このplanを含むUpdate Quiet Market Instrument UI commit自身`
- Verified tree: commit後の`HEAD^{tree}`。自己参照を避けるため正確なhashは`.ai-work/state.md`と最終報告へ記録する。
- Current checkpoint: `complete`
- Result: `PASS_ON_COMMIT`

## 1. 実装結果

監視専用境界、Candidate/OI algorithm、Watchlist、Raw Sort、Smart Rank計算、VPI-Lite+、Cold/Hot、Chart、Past Note、Dashboard設定、data-quality状態を維持した。

- Live/Fixtureの`summary.volumeRatio15m`へactive config由来のrolling 15分基準metadataを追加した。計算、`schemaVersion=1`、generated schema typeは変更していない。
- Desktop Candidateは連続4列、MobileはCSS breakpointで切り替えるautomatic activation tabsとした。`MediaQuery`によるSSR markup分岐はない。
- Watchlist分類、有限値の`×`表記、valid baseline説明、invalid fallback、15mだけのSymbol量倍率行を実装した。
- user-visible `Smart Rank`を`補正順位`へ変更し、`Raw #n → 補正 #n`を最終表示indexから出した。`smart-rank.ts`は無変更である。
- Selected detailを連続Inspectorへ軽量化し、VPI state主・補助値副、OI availability、全signal/risk/reasonを維持した。
- Dashboard/Symbolの24h rangeはdecorative gradientを廃止しneutral trackとmarkerにした。selected/focus/state insetは維持した。

## 2. Acceptance criteria

| ID | Status | Reproducible evidence |
| --- | --- | --- |
| AC-UI-001 | PASS | `git diff -- apps/web/src/lib/market/smart-rank.ts apps/scanner-core/src/prep_watchdeck/domain/screening/rankings.py`は空。focused E2E 58 PASS。 |
| AC-UI-002 | PASS | `DashboardRankingArea.svelte`のDesktop 4列。final `dashboard-1440.png`。 |
| AC-UI-003 | PASS | 560/390/320px final screenshotsとresponsive E2E。 |
| AC-UI-004 | PASS | `mobile candidate tabs use automatic roving activation` PASS。Arrow、Home、End、wrap、ARIAを検証。 |
| AC-UI-005 | PASS | `categoryCompactLabel` unitとhome E2E。全rowのlabel領域に分類を表示。 |
| AC-UI-006 | PASS | scanner metadata tests 19 PASS、Web helper 9 PASS、home valid/fallback E2E PASS。 |
| AC-UI-007 | PASS | symbol-workspace E2EでTimeframe Boardの`em`が1件かつ15m量倍率と確認。 |
| AC-UI-008 | PASS | smart-rank E2E PASS、`smart-rank.ts`無変更、Raw→補正表示確認。 |
| AC-UI-009 | PASS | final desktop/mobile visual review、home/symbol workspace E2E。market fact削除なし。 |
| AC-UI-010 | PASS | VPI scoreは補助値、state主表示。OI availability assertionとCold非再計算E2E PASS。 |
| AC-UI-011 | PASS | full gateのSTALE/PARTIAL/Past Note/Hot/Cold tests PASS。sentinel hash不変。 |
| AC-UI-012 | PASS | 1440/1200/960/560/390/320px visual reviewとresponsive overflow E2E PASS。 |
| AC-UI-013 | PASS | package/lock diffなし。新production dependency 0。 |
| AC-UI-014 | PASS | scanner 19、Web unit 19、check/build、指定focused E2E 58 PASS。 |
| AC-UI-015 | PASS | `bash scripts/verify-local.sh` exit 0: pytest 236、Web unit 183、E2E 59。 |
| AC-UI-016 | PASS | baseline/final比較と3銘柄選択実測。未解決P0/P1なし。 |
| AC-UI-017 | PASS | `DESIGN.md`、current docs、index、config READMEを同期。metadata/link tests 17 PASS。 |
| AC-UI-018 | PASS_ON_COMMIT | 本planを含む対象fileだけを明示stageし、`Update Quiet Market Instrument UI` commitとclean worktreeで成立する。 |

## 3. Checkpoints

CP-001〜CP-013はすべて完了。CP-002はPython RED 4件から19 PASS、Web helperはmissing module REDからunit PASS。Wave 1はscanner 19、Web unit 26、check/build、E2E 47 PASS後にWave 2へ進んだ。Wave 2とvisual QA、docs、full gate、final auditを完了した。

## 4. 実行証拠

- cwd `/home/tn/projects/prep-watchdeck/apps/scanner-core`: focused pytest、exit 0、`19 passed`。
- cwd `/home/tn/projects/prep-watchdeck/apps/web`: specified unit、exit 0、`19 passed`; `bun run check` 0; `bun run build` 0; focused E2E `58 passed`。
- cwd `/home/tn/projects/prep-watchdeck`: `bash scripts/verify-local.sh`、exit 0、pytest 236 / Web unit 183 / E2E 59。
- DesignMD 0.1.0: baseline/finalともexit 1でfinding集合同一。既存`colors.panelOverlay` error、unused primary warningのみ。新規finding 0。
- Visual: resolved state rootの`tmp/quiet-market-instrument/{baseline,final}`。6 viewport、390pxの4 tab、補正順位、3銘柄選択evidenceを保存。
- Sentinel: Past Note `2240c8ad...b24001`、Dashboard設定 `e1e57eb1...4fb7e`で前後一致。
- Final read-only audit: `git diff --check` 0、package/lock diff空、runtime/test artifact・secret・private/trading API・debug logなし。

## 5. 差異と判断

- `baseline_window_bars`は5分足本数ではなくrolling 15分値のsample数なので、外部metadataを`baselineSampleCount`とした。
- 既存DesignMD failureは今回と無関係なpre-existing debtで、固定version baselineとの差分0をmandatory conditionとした。
- P1 planは既存Archive手順がactive planを除外するため削除せず、indexだけ完了済み・Archive待ちへ直した。
- selected/focus/stateのinset lineとmarker outlineはsemantic stateなので削除対象外とした。

## 6. 残余リスクと残作業

- 未解決P0/P1: なし。
- 非blocking残余: DesignMD 0.1.0の既存1 error / 1 warning。今回の新規findingはない。
- production service/Web restartとdeployは明示対象外で未実施。
- screenshots、Playwright output、runtime state、`.ai-work/`はRepo外またはignoredでcommitしない。
- Remaining work: local commitとcommit後clean確認のみ。
