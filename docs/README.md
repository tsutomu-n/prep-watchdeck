# prep-watchdeck 現行ドキュメント

- 作成: `2026-06-22T06:38:13+09:00`
- 更新: `2026-08-10T20:04:38+09:00`
- 検証: `2026-08-10T20:04:38+09:00`
- 文書更新作業: `2026-08-10_20:04`（Asia/Tokyo）
- 状態: `現行`

---

このindexは、現行仕様、有効な設計判断、未完了の実装計画だけを案内する。
実装履歴、完了計画、過去検証、旧persona資料、mockupは現行仕様として扱わない。

## まず読む

- [overview.md](current/overview.md): 製品の役割、現行機能、責任範囲
- [ui-workflow.md](current/ui-workflow.md): shared themeとsemantic color、DashboardのDOM・focus順、
  row選択と個別分析遷移、全signal/stale、Candidate/WatchlistのMobile密度、Symbol local nav/chart、
  Monitoring Rail、Past Noteのmutation lock・symbol scope・revision保持
- [operations.md](current/operations.md): 起動、service、state root、停止条件

## 現行仕様

- [architecture.md](current/architecture.md): scanner-core、Web、Cold/Hot/chart lane
- [data-contracts.md](current/data-contracts.md): snapshot、service state、chart、ticker、monitoring state、API
- [validation.md](current/validation.md): full gate、performance、soak、state移行検証
- [documentation.md](current/documentation.md): 文書の正本、更新trigger、local workflow artifact、再構成・Archive条件
- [../DESIGN.md](../DESIGN.md): shared token、semantic color、42/82px密度、touch、responsive構造、
  chart、Monitoring Rail、Past Note、誤推奨防止のdesign contract
- [scanner filter README](../config/scanner-filters/README.md): filter template

## 設計判断

- [0001 Local-first](decisions/0001-local-first.md)
- [0002 Bitget public API only](decisions/0002-public-api-only.md)
- [0003 Cold snapshot / Hot ticker](decisions/0003-cold-hot-data-lanes.md)
- [0004 Snapshot / Chart世代整合](decisions/0004-chart-generation-consistency.md)
- [0005 自動売買を含めない](decisions/0005-no-automatic-trading.md)
- [0006 VPI-Lite+ Cold sidecar](decisions/0006-vpi-lite-plus-cold-sidecar.md)
- [0007 市場監視専用の製品境界](decisions/0007-monitoring-only-product-boundary.md)
- [0008 Candidate 74h ANDとOI 60分契約](decisions/0008-candidate-oi-contract.md)

## 実装・検証計画

- [P1 Candidate / OI契約修正](plans/active/p1-candidate-oi-contract/README.md): 74h Candidate条件、OI 60分変化、最小UI・テスト・初期runtime qualificationを完了済み。安全な履歴Archive待ちのliving plan。
- [Quiet Market Instrument](plans/active/quiet-market-instrument/IMPLEMENTATION_PLAN.md): Candidate、Watchlist、Inspector、補正順位の表示契約を同期する現行living plan。

監視専用化の完了計画と過去検証証拠はRepo外Archiveへ退避し、
現行仕様は`docs/current/`、有効な判断はADR 0007とADR 0008を正本とする。

## 正本の優先順位

1. 現行code、schema、tests、CLI help
2. `docs/current/`
3. `docs/decisions/`
4. `docs/plans/active/`

固定されたruntime件数、market値、process状態は文書を正本にしない。
`watchdeck doctor`、state files、実process、実画面で確認する。

## 旧文書の扱い

旧文書とmockupは、現行事実と有効な判断を上記へ抽出した後、
`scripts/maintenance/archive-repo-history.sh`でRepo外へcopyし、相対path SHA-256を
照合してからGit追跡を外す。

archive copyが完了するまではsourceを削除しない。旧文書へ直接linkを追加せず、
現行仕様の更新は`docs/current/`へ行う。
