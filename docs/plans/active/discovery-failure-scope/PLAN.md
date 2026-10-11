# DiscoveryとRecoveryの限定修正
timestamp="2026-10-11(日)_10:39 JST"

- 作成: `2026-10-11T10:39:13+09:00`
- 更新: `2026-10-11T10:39:13+09:00`
- 検証: `未検証`
- 状態: `実装計画`

## Goalとscope

2026-10-11の現状調査から、利用可能な対象や未保存の判断を別の失敗で失わないようにする。
基点はsource `487033c`。ユーザーの「すすめて」を、提示済みの小さなlocal修正を進める指示として扱う。
このplanはsource修正・必要な隔離検証・commitまでを対象にする。

1. Hyperliquidの履歴上限を対象単位の診断として残し、他VenueのRecoveryを継続する。
2. 比較workspaceと判断historyを独立して読み、失敗側だけ再取得する。history不明時は判断保存を止め、正常なpinを保持する。
3. 判断の対象・episode・固定snapshot・理由を一組の下書きとして保護する。切替とnavigationでも元の根拠を勝手に更新しない。
4. 保存済みsource capabilityから、OI未対応・契約未確認と取得可能なendpointの欠損を区別する。nullを保持し、UIでも理由を確認できる。

本番反映、unit操作、live DB/Provider操作、push/PR/CI、旧versionの新writer、Attention score変更、統計評価契約変更は対象外。
スコア・評価・長期容量・新7200秒受入は調査提案の別段階であり、この限定修正の合格へ混ぜない。

## 完了条件

- 古い手動窓でHyperliquidだけがhistory limitとなり、他Venueをscan/repairできる。未確認件数を0と表示せず、partialと対象診断を保持する。
- 判断historyだけの500とその回復で、保存pinを維持し、履歴不明な判断保存を許可しない。再取得で復帰する。
- 理由入力後の別判断、navigationと再読込で、対象・episode・理由・元snapshotを保持するか明示破棄する。正常保存後だけ該当下書きを除く。selectionへ自動POSTしない。
- unavailableなOI capabilityはunsupportedと理由で示し、available/unknown capabilityの実欠損はmissingのまま。trade changeとidentityは変えない。
- 対象回帰、Market Ruff/format/Pyrefly、Web test/check/build、関連Desktop/Mobile E2Eとdoc checkerが合格する。失敗・未実施は区別する。
- 元workspaceの4件の未commit差分を保全し、今回の差分だけcommitする。完了後は現行仕様へ最小限反映し、このplanをactiveから除く。

## Checkpointとownership

- 既存差分を確認済み。cleanな隔離worktreeで専用branchを作成した。
- Recovery担当: candle recovery本体と近接pytest。
- Metrics担当: Market OI projection、近接pytest、nativeの理由表示と必要な近接Web検証。
- Discovery担当: 比較componentと必要な下書きhelper/近接E2E。
- Primary: 統合diff、生成物、docs、隔離検証、レビュー、commit、保全確認。
- 現在: 実装前。最小限の原因再現をREDとして記録する。

## 検証とrollback

試験DB・state・Web portは現役serviceから隔離する。既存依存を使い、新依存やtoolchain upgradeを行わない。
sourceの差分を小さく分け、回帰は実フローの観測結果を検証する。実装の字面を照合するtestは追加しない。
rollbackは今回のsource commitを将来の反映対象から外すか、反映済みの場合に別途承認されたrelease rollbackで行う。
user変更の破棄・hard reset・clean・stashや本番stateの削除は行わない。

## 未解決事項

今回の不具合修正は、PEARL/旧履歴の審査、候補map資格、運用承認、採用後の2時間観測、30日prospective evidenceを完了させない。
下書きの復元・障害再取得の細部は、既存フローと回帰を読んで最小に確定する。
