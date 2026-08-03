# prep-watchdeck 現行ドキュメント管理

- 作成: `2026-07-18T11:29:04+09:00`
- 更新: `2026-08-02T22:00:39+09:00`
- 検証: `2026-08-02T22:00:39+09:00`
- 文書更新作業: `2026-08-02_22:00`（Asia/Tokyo）
- 状態: `現行`

---

## 対象と正本

対象はGit追跡中、またはignoreされていない未追跡の人向けMarkdown / HTMLである。
runtime state、生成物、Repo外Archive、`.ai-work/`、完了計画、過去検証artifactは
現行文書へ数えない。

内容が衝突した場合は次の順で判断する。

1. 現行code、schema、config、tests、CLI help
2. `docs/current/`
3. `docs/decisions/`
4. `README.md`と対象directoryのREADME

固定されたprocess ID、市場件数、snapshot件数、test件数、benchmark値は現在値の正本に
しない。実process、state artifact、その時点のtest出力で確認する。

## Local workflow artifact

- repo rootの`HANDOFF.md`は、未commit作業がある間だけ使う短期の再開正本である。
  branch、HEAD、差分、次のactionをcurrent worktreeへ合わせ、現行仕様の代わりにはしない。
- `.ai-work/`と`.codex/SP_STATE.md`はactive checkpointと実装範囲の作業証拠である。
  対応する未commit差分が残る間は、完了済み計画と誤認して削除しない。
- `.plan/`と`.ai_memory/`はgitignoredの旧計画・旧handoff置場であり、現行仕様や再開正本に
  しない。root handoffとbranch / HEADが食い違う内容はstaleとして扱う。
- `apps/web/src/app.html`はSvelteKitのsource templateであり、人向け文書監査へ含めない。

旧local artifactを整理する時は、有効な判断をcurrent docまたはroot handoffへ抽出し、
Repo外Archiveへ相対pathを保って複製し、manifestとSHA-256を照合してからsource削除を判断する。
ignoredであることだけを削除根拠にしない。

## 文書の役割と更新trigger

| 文書 | 役割 | 主な正本 | 更新trigger |
| --- | --- | --- | --- |
| `README.md` | 最短起動と利用入口 | 起動script、CLI help、state path実装 | 起動方法、主要option、利用導線の変更 |
| `AGENTS.md` | Repo作業規則 | 実際のtoolchain、test command、directory | toolchain、構成、検証規則の変更 |
| `DESIGN.md` | UIの規範 | 採用済みUI原則と実装 | token、component、interaction規則の変更 |
| `config/scanner-filters/README.md` | filter template説明 | 3 TOMLとscreening code | template field、閾値、ranking意味の変更 |
| `docs/README.md` | 現行文書index | 存在する現行文書 | 文書の追加、改名、削除、役割変更 |
| `docs/action-required.md` | ユーザー判断が必要な未解決事項 | 現在の作業状態と停止条件 | 新規blocker、判断完了、再開条件の変更 |
| `docs/current/overview.md` | 製品責任範囲と機能一覧 | code、routes、CLI | user-visible機能またはnon-goalの変更 |
| `docs/current/architecture.md` | process、lane、state境界 | scanner/Web構成、runtime code | 責任境界、task、storage、data laneの変更 |
| `docs/current/data-contracts.md` | schema、artifact、API契約 | schema、DTO、repository、API routes | field、version、route、method、validationの変更 |
| `docs/current/operations.md` | 起動、service、state、復旧 | CLI help、shell script、runtime policy | 運用option、path、停止・復旧条件の変更 |
| `docs/current/ui-workflow.md` | 利用者の監視フロー | routes、components、annotation contract | 主要画面、監視annotation、view設定の変更 |
| `docs/current/validation.md` | 現行gateと完了判定 | test config、`verify-local.sh` | test suite、acceptance、evidence方針の変更 |
| `docs/decisions/*.md` | 現在も有効な設計判断 | codeと採用済み制約 | 判断の置換、撤回、責任範囲変更 |

## 監査時の分類

### 現状維持

codeとの不一致がなく、役割も重複していない文書は内容を変えない。監査したという理由
だけで`更新`を進めない。個別監査の分類結果はcurrent policyではなく作業証拠へ残す。

### 局所更新

一部のoption、route、path、field、linkだけが古い場合は、正本へ直接対応する箇所だけを
直す。

### 再構成

現行仕様、操作手順、一回限りの検証ログが混在し、局所修正では役割を分離できない場合は
作り直す。現行文書にはgateと合否条件を残し、実行証拠は完了計画、handoff、
Repo外Archiveへ分離する。

### Archive後に削除または作り直す

完了したaction handoff、置換済み仕様、完了計画、過去検証、旧mockupは現行導線に残さない。
必要な事実をcurrent docまたはdecisionへ抽出し、Repo外へ複製してSHA-256を照合してから
Git追跡を外す。継続利用するledger pathは、完了済み本文をArchiveした後に最小の現行内容へ
作り直す。未完了作業、rollbackに必要な唯一の手順、未移行の有効判断は削除しない。

## 監査手順

1. `git status --short --branch --untracked-files=all`で既存差分を固定する。
2. metadata checkerの`workingTreePaths`と`isDocumentTarget`でtrackedおよびignoreされていない
   未追跡文書を列挙する。
3. CLI help、Web route、schema、config、test、scriptへ各主張を照合する。
4. 現状維持、局所更新、再構成、Archive後に削除へ分類する。
5. 文書metadata、local link、関連test、full local gateを実行する。
6. 固定runtime値、完了済みhandoff、存在しないpath、重複した正本を再検索する。
7. root `HANDOFF.md`、`.ai-work/`、`.codex/SP_STATE.md`、`.plan/`、`.ai_memory/`の
   branch、HEAD、goal、参照元を確認し、active stateとlegacy artifactを分ける。

文書だけの変更でも、内容がcode truthと一致することはmetadata/link checkerだけでは
証明できない。CLI help、route inventory、schemaまたは対象testを別に確認する。
