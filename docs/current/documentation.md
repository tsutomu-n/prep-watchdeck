# prep-watchdeck 現行ドキュメント管理

- 作成: `2026-07-18T11:29:04+09:00`
- 更新: `2026-08-15T11:04:37+09:00`
- 検証: `2026-08-15T11:04:37+09:00`
- 状態: `現行`

---

## 正本

衝突時は次の順で判断する。

1. 現行code、schema、migration、tests、CLI help
2. `docs/current/`
3. `docs/decisions/0011-perp-universe-replacement.md`
4. `README.md`とactive plan

固定されたmarket件数、PID、artifact時刻、test件数、benchmark値は文書を正本にしない。
実service、DB、artifact、実画面、その時点のtest出力で確認する。

`docs/current/`の「現行」はRepositoryに実装された現行仕様を表す。commit、push、merge、live cutoverは
別の状態であり、現在hostで稼働中のversionと混同しない。

## 文書の役割

| 文書 | 役割 | 更新trigger |
| --- | --- | --- |
| `README.md` | 最短setup、起動、state、maintenance | CLI、script、unit、主要導線 |
| `AGENTS.md` | Repo作業規則 | directory、toolchain、gate |
| `DESIGN.md` | semantic tokenとUI規範 | component、interaction、responsive |
| `docs/README.md` | 現行文書index | 文書の追加、削除、役割変更 |
| `docs/current/user-manual.md` | 利用者の操作・読み方とAI向け最小参照 | user-visible機能、表示、主要導線 |
| `docs/current/overview.md` | 製品価値と責任範囲 | user-visible機能、対象Venue、市場範囲 |
| `docs/current/architecture.md` | process/storage/data lane | service、DB、artifact、state境界 |
| `docs/current/data-contracts.md` | identity、schema、API | field、version、route、retention |
| `docs/current/ui-workflow.md` | 主要操作とfail-closed表示 | flow、selection、Chart、Past Note |
| `docs/current/operations.md` | setup、systemd、backup、rollback | path、unit、operational policy |
| `docs/current/validation.md` | gateと合否条件 | test suite、acceptance、evidence |
| `docs/decisions/*.md` | 採用済み設計判断 | 判断の置換、撤回、互換性変更 |

`docs/current/`へ将来予定、一回限りのPID/件数、未検証のlive主張を置かない。未完了checkpointと
証拠はactive plan、短期再開情報が必要なtaskだけroot `HANDOFF.md`へ分ける。

## 旧仕様

Decision 0003、0004、0006〜0010と旧scanner関連の文書は、Decision 0011がproduction契約を
置換した履歴である。rollbackに必要な旧unit/state/checkout情報は削除しないが、現行起動、
データ契約、UIの導線へ混ぜない。

旧state migration/archive scriptは旧runtime rollback資産を保存するため残る場合がある。
存在だけを現行scanner機能の根拠にしない。

## 更新手順

1. `git status --short`と対象diffを確認する。
2. CLI help、schema、migration、route、unit、scriptへ主張を照合する。
3. 現行事実だけを局所更新し、過去証拠と将来計画を分離する。
4. metadata/link checkerと変更箇所のfocused gateを実行する。
5. 置換済みpath、固定runtime値、壊れたlocal linkを再検索する。

```bash
bun test scripts/maintenance/document-metadata.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun test scripts/maintenance/document-links.test.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
```

metadata/link greenは内容の正しさを証明しない。実装正本との照合を別に行う。
