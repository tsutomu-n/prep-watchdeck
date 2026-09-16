# prep-watchdeck 現行ドキュメント

- 作成: `2026-06-22T06:38:13+09:00`
- 更新: `2026-09-16T22:14:16+09:00`
- 検証: `2026-09-16T22:14:16+09:00`
- 状態: `現行`

---

このindexは、現行production runtimeと、今後のWatchdeck製品境界を分けて案内する。
固定されたmarket件数、PID、artifact時刻、test件数、benchmark値を将来の製品制約にしない。

## 最初に読む

- [product-boundary.md](current/product-boundary.md): **製品境界と将来拡張の最優先正本**
- [0012 Product evolution boundary](decisions/0012-product-evolution-boundary.md): 製品境界更新の設計判断
- [user-manual.md](current/user-manual.md): 現行production UIの操作・読み方
- [overview.md](current/overview.md): 現在の製品価値とproduction実装範囲
- [architecture.md](current/architecture.md): 現行market-core、Postgres、Parquet、artifact、Webの境界

## 現行runtime仕様

- [data-contracts.md](current/data-contracts.md): 現在実装済みのidentity、保存単位、schema、API
- [ui-workflow.md](current/ui-workflow.md): 現在実装済みのUniverse、selection、Chart、depth/trade、Past Note
- [operations.md](current/operations.md): 専用Postgres、systemd、state、maintenance、backup、rollback
- [validation.md](current/validation.md): focused / full / runtime validation
- [documentation.md](current/documentation.md): 文書の正本と更新規則
- [watchdeck-v1-scope.md](current/watchdeck-v1-scope.md): 完成済みv1 P0 baselineと当時のscope記録
- [../DESIGN.md](../DESIGN.md): 現行visual defaultsと維持するUX/accessibility原則

上記runtime文書にあるVenue数、timeframe、bar数、selection数、depth/trade件数、artifact数、retention、
localhost配置等は現在実装を説明する。`product-boundary.md`に反する形で永久禁止として解釈しない。

## 有効な設計判断

- [0001 Local-first](decisions/0001-local-first.md): local-firstを維持。古いstorage実装詳細は現行契約ではない
- [0005 自動executionを含めない](decisions/0005-no-automatic-trading.md): ranking/scoreは許可し、既定で自動注文へ接続しない
- [0011 3 Venue Perp Universeへ置換](decisions/0011-perp-universe-replacement.md): **現行Perp runtimeのarchitecture baseline**
- [0012 製品境界を拡張可能な裁量支援へ更新](decisions/0012-product-evolution-boundary.md): **将来の製品境界**
- [/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/docs/decisions/0013-independent-ranking.md](decisions/0013-independent-ranking.md): 固定参照ランキングと資格判定の分離。
- [/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/docs/decisions/0014-native-chart-history.md](decisions/0014-native-chart-history.md): native履歴・時間足とJST基準騰落率。

Decision 0002およびDecision 0003、0004、0006〜0010は当時の設計履歴として参照できるが、Decision 0012と
現行product boundaryに反する部分を将来機能の禁止根拠にしない。

## 実装計画

ランキング・チャート統合とD05稼働受入は完了した。現行の運用・検証正本へ結果を反映し、
完了planは削除した。過去の要求・試行・証拠台帳はPR #15のGit履歴で参照する。

`docs/plans/active/<task>/`には未完了で再開対象のplanだけを置く。完了、中止、置換後は現行treeから削除し、
過去planはGit履歴で参照する。

## 正本の優先順位

製品境界・将来機能の可否:

1. `docs/current/product-boundary.md`
2. `docs/decisions/0012-product-evolution-boundary.md`
3. 現行code/schemaの実装上の事実
4. その他の`docs/current/`
5. Decision 0011以前の履歴

現在productionの挙動:

1. 現行code、schema、migration、tests、CLI help
2. 対応する`docs/current/`
3. Decision 0011

現在の稼働状態はsystemd、service log、DB、artifact、実画面で確認する。
