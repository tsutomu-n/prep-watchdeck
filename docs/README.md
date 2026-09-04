# prep-watchdeck 現行ドキュメント

- 作成: `2026-06-22T06:38:13+09:00`
- 更新: `2026-09-04T20:49:47+09:00`
- 検証: `2026-09-04T20:49:47+09:00`
- 状態: `現行`

---

このindexは、3 Venue Perp Universe Explorerの現行仕様と有効な設計判断を案内する。
固定されたmarket件数、PID、artifact時刻、test件数は現行事実として置かない。

## まず読む

- [user-manual.md](current/user-manual.md): 人間向けの操作・読み方とAI向け最小参照をまとめた正本
- [watchdeck-v1-scope.md](current/watchdeck-v1-scope.md): v1 P0の責務、完成条件、scope freeze
- [overview.md](current/overview.md): 製品価値、対象市場、責任範囲
- [ui-workflow.md](current/ui-workflow.md): Universeの絞り込み、選択、Chart、板・約定、Past Note
- [operations.md](current/operations.md): 専用Postgres、systemd、state、Funding同期、maintenance、rollback

## 現行仕様

- [architecture.md](current/architecture.md): market-core、Postgres、Parquet、artifact、Webの境界
- [data-contracts.md](current/data-contracts.md): identity、保存単位、Funding、4 JSON、local write API
- [validation.md](current/validation.md): focused gate、full gate、isolated smoke/shadow
- [documentation.md](current/documentation.md): 文書の正本と更新規則
- [../DESIGN.md](../DESIGN.md): theme/fontを維持したUniverse Explorerのdesign contract

## 有効な設計判断

- [0001 Local-first](decisions/0001-local-first.md)
- [0002 public API only](decisions/0002-public-api-only.md)
- [0005 自動売買を含めない](decisions/0005-no-automatic-trading.md)
- [0011 3 Venue Perp Universeへ置換](decisions/0011-perp-universe-replacement.md)

Decision 0011は、旧Bitget scanner、DuckDB snapshot、Candidate/Ranking、VPI、Hot ticker、
3市場pilotに関するDecision 0003、0004、0006〜0010のproduction契約を置換する。旧Decisionは
履歴とrollback文脈として残すが、現行実装の導線にはしない。

## 実装計画

現在進行中のactive planはない。`docs/plans/active/<task>/`は未完了作業が開始された場合だけ作成し、
完了、中止、または置換後は現行treeから削除する。過去planはGit履歴で参照する。

## 正本の優先順位

1. 現行code、schema、migration、tests、CLI help
2. `docs/current/`
3. `docs/decisions/0011-perp-universe-replacement.md`
4. 現在進行中のactive plan（存在する場合）

現在の稼働状態はsystemd、service log、DB、`artifacts/service-state.json`、実画面で確認する。
