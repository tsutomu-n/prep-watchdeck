# 実装順序と完了証拠

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

全作業単位が必須。番号は中間版の納品を意味しない。変更前に実物と既存テストを確認し、該当する既存実装は再利用する。

| 作業 | 実装と接続 | 必須証拠 |
| --- | --- | --- |
| W0 整合確認 | baseline差分、AGENTS、既存source/table/route、plan、用語と採否 | 対応表、未確認、変更scope |
| W1 契約 | 新schema、Pydantic、生成TS、profile定義/version/hash、reason | malformed/unknown/NaN/time/instrument rejection |
| W2 入力・計算 | 1m連続窓、version、volume median、3profile、順位/欠測、scope completeness | R01〜R06、fixture値と独立expected |
| W3 保存 | additive migration、immutable run、decision idempotency、evidence revision、archive/readback | transaction、conflict、restore、retention試験 |
| W4 runtime | 保存後trigger、bounded worker、queue/cancel、寿命、atomic publish、再起動recovery | 2連続cycle、旧collector非退行、停止/timeout試験 |
| W5 研究 | 毎時観測、forward outcome、baseline、censor、共通guard、bootstrap、query/results/export | H01〜H07、future leakage、全出口一致 |
| W6 外部情報 | Fed real schema、manifest/data revision固定、bounded fetch/import、terms、source health | E01〜E05、実response smoke、revision再読込み |
| W7 Web/API | producer read model、job control、decision保存確認、画面、Chart導線、原典、export | U01〜U04、desktop/narrow E2E |
| W8 運用・終了 | 状態表示、容量、migration/restore/disable、現行docs/Decision、全体gate | O01〜O05、要求ID→試験/出力path |

W2はW1後、W3/W6は契約確定後に進める。W4は保存整合を壊さない形でW3に接続し、W5/W7を同じapplication resultへ統合する。UIとCLIが別計算式を持たない。

## 必ず確認する落とし穴

- all instrumentsのhistoryを毎分全再走査しない。完了足の更新を使って必要窓だけ計算し、同じwatermark/definitionは再利用する。
- 即時計算結果だけでなく除外理由とscope母数を保存する。取得失敗で除外銘柄が消えたことを上位銘柄の改善に見せない。
- 手動decisionをDB commitする前にWebへ成功を返さない。worker再起動で二重保存しない。
- 過去queryが現行catalogだけをJOINして、当時存在したが今inactiveなinstrumentを消さない。
- source公開日、pipeline取得日、ローカル初回確認日を混同しない。
- JSONだけatomicでもDBと不整合になるので、再発行可能な順序と復旧を試験する。

## 最終diffレビュー

依存増加、生成物の手編集、秘密情報、production path固定、無断ネットワーク取得、古いガードの緩和、無関係なrefactorを確認する。fixturesによる値が通常runtimeから到達しないことを確認する。run/record/resultの互換性と保存寿命も確認する。

受入証拠はplanで管理し、完了時は現行文書へ移す。本パックへ実装済みと書き換えるだけで試験証拠の代わりにしない。外部制約で未達が残る場合、当該IDと復帰条件を明記し全体完了としない。
