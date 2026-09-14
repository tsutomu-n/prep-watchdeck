# prep-watchdeck 現行ドキュメント管理

- 作成: `2026-07-18T11:29:04+09:00`
- 更新: `2026-09-14T22:34:31+09:00`
- 検証: `2026-09-14T22:34:31+09:00`
- 状態: `現行`

---

## 正本を2種類に分ける

### 製品境界・将来機能の可否

衝突時は次の順で判断する。

1. `docs/current/product-boundary.md`
2. `docs/decisions/0012-product-evolution-boundary.md`
3. 現行code/schemaが示す実装上の事実
4. その他の`docs/current/`
5. Decision 0011以前の設計履歴

旧P0のscope freeze、ranking禁止、新Venue/aggregator禁止、Stocks/RWA禁止、paid/read-only API禁止、
ML/backtest禁止、trade-support identifier禁止、固定timeframe/bar数等は将来機能の拒否理由にしない。

### 現在productionの挙動

1. 現行code、schema、migration、tests、CLI help
2. 対応する`docs/current/`
3. Decision 0011
4. READMEとactive plan

実service、DB、artifact、実画面、その時点のtest出力でruntime状態を確認する。

`docs/current/`の「現行」はRepository上の現在仕様を表し、現在hostのdeploy版と同義ではない。

## 現在値を永久制約にしない

次のような値は文書へ現行事実として書けるが、特に明示しない限り製品憲法ではない。

- Venue数、asset class、source数
- poll周期、timeout、TTL、heartbeat
- timeframe、bar数、depth段数、trade件数
- selection件数、book-walk notional
- artifact数、route数、schema version
- retention日数、archive generation保持数
- port、path、systemd unit、DB配置
- theme、radius、shadow、gradient、layout、badge用途等のvisual default

変更時にはその変更に必要なrate limit、capacity、migration、data quality、rollbackを検証する。

## 文書の役割

| 文書 | 役割 | 更新trigger |
| --- | --- | --- |
| `README.md` | 最短setupと現行runtime入口 | CLI、script、unit、主要導線 |
| `AGENTS.md` | AI/開発者の作業規則と正本優先順位 | boundary、directory、toolchain、gate |
| `DESIGN.md` | 現行visual defaultsとUX/accessibility原則 | component、interaction、responsive、visual system |
| `docs/README.md` | 現行文書index | 文書追加、削除、役割変更 |
| `docs/current/product-boundary.md` | 製品境界・許可される将来拡張 | product direction、永久制約の変更 |
| `docs/current/user-manual.md` | 現行UIの操作・読み方 | user-visible実装 |
| `docs/current/overview.md` | 現在の製品価値と実装範囲 | user-visible機能、市場範囲 |
| `docs/current/architecture.md` | 現行process/storage/data lane | service、DB、artifact、state境界 |
| `docs/current/data-contracts.md` | 現行identity、schema、API | field、version、route、retention |
| `docs/current/ui-workflow.md` | 現行主要操作とfail-closed表示 | flow、selection、Chart、notes |
| `docs/current/operations.md` | 現行setup、systemd、backup、rollback | path、unit、operational policy |
| `docs/current/validation.md` | 現行gateと合否条件 | test suite、acceptance、evidence |
| `docs/current/watchdeck-v1-scope.md` | 完成済みP0 baselineの意味 | P0履歴解釈 |
| `docs/decisions/*.md` | 採用済み設計判断とsupersede関係 | 判断の置換、撤回、互換性変更 |

固定されたPID、実行時row件数、artifact timestamp、単発benchmark、backup hash等の一回限りの証拠を
`docs/current/`の恒久仕様として増やさない。必要ならactive plan、PR、release evidenceへ置く。

## Active plan lifecycle

`docs/plans/active/<task>/`には未完了checkpointまたは未解決事項があり再開対象のplanだけを置く。
完了、中止、置換済みplanを履歴としてactiveへ残さない。

Planを閉じる前に、残る現行事実を`docs/current/`、採用済み判断を`docs/decisions/`へ反映する。
過去の計画、検証値、当時の判断はGit履歴から参照する。

## 旧仕様の扱い

Decision 0003、0004、0006〜0010と旧scanner関連は履歴である。Decision 0011は現行Perp runtimeの
architecture baselineとして有効だが、Decision 0012が製品境界部分をsupersedeする。

旧state migration/archive script、旧unit/state/checkoutはrollbackやデータ保全のため残る場合がある。
存在だけを現行機能や将来禁止の根拠にしない。

## 更新手順

1. `git status --short`と対象diffを確認する。
2. product boundary変更か、現行runtime変更かを最初に分類する。
3. CLI help、schema、migration、route、unit、scriptへ現行runtime主張を照合する。
4. 古い禁止・固定値がCI、schema、test、AGENTS、DESIGNへ重複していないか検索する。
5. 完了・中止・置換済みplanをactiveから除く。
6. metadata/link checkerと変更箇所のfocused gateを実行する。
7. 置換済みpath、固定runtime値、壊れたlocal link、supersede漏れを再検索する。

```bash
bun test scripts/maintenance/document-contracts.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
```

metadata/link greenは内容の正しさを証明しない。製品境界と実装正本の両方へ照合する。
