# Repository Guidelines

- 作成: `2026-06-26T16:12:22+09:00`
- 更新: `2026-08-02T22:00:39+09:00`
- 検証: `2026-08-02T22:00:39+09:00`
- 状態: `現行`

---

## Project Structure & Module Organization

`prep-watchdeck` is a local-first monorepo. Python scanner code lives in `apps/scanner-core/src/prep_watchdeck`, with tests in `apps/scanner-core/tests`. The SvelteKit frontend lives in `apps/web/src`, with browser tests in `apps/web/tests/e2e`. Shared filter templates are in `config/scanner-filters`, JSON schema output is in `schemas`, fixture data is in `fixtures`, and current documentation is indexed from `docs/README.md`. Runtime state is rooted at `PREP_WATCHDECK_STATE_DIR`, with repo `var/` used only as the compatibility fallback. Runtime files, `.svelte-kit`, `node_modules`, and test results are not source.

## Build, Test, and Development Commands

- `bash scripts/start-all.sh`: create a live snapshot, generate web types, and start the local web UI.
- `SNAPSHOT_SOURCE=fixture bash scripts/start-all.sh`: start without live network data.
- `cd apps/scanner-core && uv run watchdeck status`: check scanner-core storage and snapshot state.
- `cd apps/scanner-core && uv run watchdeck scan --source fixture --fixture-set basic --template balanced`: produce a deterministic fixture snapshot.
- `cd apps/web && bun run generate:types`: regenerate TypeScript types from `schemas/scanner-snapshot.schema.json`.
- `bash scripts/verify-local.sh`: run the full local gate for scanner-core and web.

## Coding Style & Naming Conventions

Use Python 3.13 and `uv` for Python commands. Python formatting is Ruff-managed: 100-character lines, spaces, and double quotes. Keep package code under `prep_watchdeck` and prefer explicit module names such as `service_deep_backfill.py`. Use Bun for frontend dependencies and scripts. Svelte components use PascalCase filenames; TypeScript helpers and tests use kebab-case or descriptive lower-case names already present in `apps/web/src/lib`.

## Testing Guidelines

Scanner tests use pytest and live tests are marked with `live`. Prefer `uv run python -m pytest -q` over bare `pytest`. Web unit tests use Vitest via `bun test`; E2E tests use Playwright via `bun run test:e2e`. Name Python tests `test_*.py`, TS unit tests `*.test.ts`, and Playwright specs `*.e2e.ts`. Run focused tests for small changes and `bash scripts/verify-local.sh` before broad releases.

## Commit & Pull Request Guidelines

Recent commits use concrete imperative subjects, usually starting with `Add` or `Update`, and mention the affected behavior or docs. Keep commits scoped. PRs should include the user-visible change, verification commands run, known residual risk, and screenshots for UI changes. Link related issues or docs when applicable.

## Security & Configuration Tips

This project uses Bitget public market data only. Do not add private API keys, balances, positions, or order endpoints. Avoid duplicate writers against the resolved `watchdeck.duckdb`; do not start another `watchdeck service` or live scan while a service writer is active. E2E, performance, and soak state must stay under the resolved state root's `tmp/` subtree.


# AI開発作業ルール

このリポジトリで作業するAIエージェントは、以下のルールに従う。

## 基本方針

ユーザーからゴールが与えられたら、ユーザーの追加アクションなしで進められる範囲を最大限進め、ゴール達成を目指す。

質問で作業を止めない。判断が必要な事項が出た場合は、以下の優先順位で処理する。

1. 既存コード・既存ドキュメント・既存テストから判断する
2. 安全で保守的な仮定を置いて進める
3. 複数案を比較し、リスクが小さい案を採用する
4. ユーザー判断が必須の事項のみ `docs/action-required.md` に記録する

## 禁止事項

以下は、明示指示がない限り実行しない。

* 課金が発生する操作
* 本番環境へのデプロイ
* 外部サービスへのデータ送信
* 秘密情報・認証情報・APIキーの作成、変更、削除
* 既存データの不可逆削除
* `git push`
* ユーザー作業中の変更の上書き
* 目的と無関係な大規模リファクタ

## 許可事項

ゴール達成に必要で、禁止事項に該当しない範囲では、以下を許可する。

* 既存コードの変更
* 必要な新規ファイルの作成
* テストの追加・修正
* ドキュメントの作成・更新
* 依存関係の追加・入れ替え
* 破壊的変更
* アーキテクチャ変更
* 内部実装の大幅な整理

ただし、依存関係の追加・入れ替え・破壊的変更・アーキテクチャ変更を行う場合は、必ず専用ブランチを作成してから作業する。

## ブランチ作業ルール

作業開始時に、まず現在のGit状態を確認する。

```bash
git status --short
git branch --show-current
```

### 専用ブランチが必要な作業

以下のいずれかに該当する場合は、必ず専用ブランチを作成してから作業する。

* 破壊的変更
* 依存関係の追加・削除・大幅な入れ替え
* ディレクトリ構成の変更
* アーキテクチャ変更
* 既存API・関数・型・DBスキーマの変更
* 大規模リファクタ
* 複数ファイルにまたがる仕様変更
* 既存挙動を変える可能性がある変更

### ブランチ名

ブランチ名は以下の形式にする。

```txt
ai/<task-slug>-YYYYMMDD-HHMM
```

例：

```txt
ai/refactor-auth-flow-20260626-1615
ai/breaking-schema-cleanup-20260626-1615
ai/replace-state-layer-20260626-1615
```

### ブランチ作成

作業前に専用ブランチを作成する。

```bash
git switch -c ai/<task-slug>-YYYYMMDD-HHMM
```

既に適切なAI作業ブランチ上にいる場合は、新しいブランチを作らず、そのブランチで続行してよい。
ただし、ブランチ名・現在の状態・続行理由を `.ai-work/state.md` に記録する。

## 既存の未コミット変更の扱い

作業開始時点で未コミット変更がある場合は、絶対に上書きしない。

まず以下を実行して状態を記録する。

```bash
git status --short
git diff --stat
```

必要に応じて、作業前の差分を `.ai-work/pre-existing.diff` に保存する。

```bash
git diff > .ai-work/pre-existing.diff
```

未コミット変更がゴールに関係する可能性がある場合は、それを前提として慎重に作業する。

未コミット変更がゴールと無関係で、作業の衝突リスクが高い場合は、無理に変更せず、`docs/action-required.md` に判断事項として記録する。

## コミットルール

`git push` は禁止する。

ローカルコミットは、ユーザーが明示的に許可した場合、または作業単位を安全に保存する必要がある場合のみ行ってよい。

ローカルコミットを行う場合は、以下を守る。

* `.ai-work/` をコミットしない
* 秘密情報を含めない
* テストまたは確認結果を記録してからコミットする
* コミットメッセージは作業内容が分かるものにする

例：

```txt
ai: implement checkpoint 01 data model cleanup
ai: add regression tests for import flow
ai: update docs for breaking config change
```

## 作業状態の管理

作業開始時に `.ai-work/` を作成する。

`.ai-work/` は一時作業メモ用であり、`.gitignore` 対象にする。

最低限、以下を作成・更新する。

* `.ai-work/state.md`
* `.ai-work/checkpoints.md`
* `.ai-work/notes.md`

`.ai-work/state.md` には以下を記録する。

* ゴール
* 現在のブランチ
* 作業開始時のGit状態
* 現在のチェックポイント
* 完了済みチェックポイント
* 未完了チェックポイント
* 重要な判断
* 未解決事項
* 最終更新内容

## 作業ループ

ゴール達成まで、以下のループを繰り返す。

### 1. Diagnose

現状を調査する。

確認対象：

* ディレクトリ構成
* 主要ファイル
* 既存仕様
* 既存ドキュメント
* 既存テスト
* ビルド・lint・型チェック設定
* ゴールに関係する実装箇所
* 壊してはいけない既存挙動
* 現在のGitブランチ
* 作業開始時点の未コミット変更

ゴールとの差分を整理し、完了判定可能なチェックポイントに分割する。

各チェックポイントには以下を持たせる。

* ID
* 目的
* 依存関係
* 対象ファイル
* 完了条件
* 想定リスク
* 破壊的変更の有無
* ブランチ作業の要否

### 2. Select

未完了チェックポイントのうち、依存関係上もっとも近いものを1つ選ぶ。

複数チェックポイントを同時に処理しない。
ただし、分離すると不自然・非効率・危険な場合は、理由を記録した上でまとめて処理してよい。

対象チェックポイントが破壊的変更を含む場合は、専用ブランチ上で作業していることを確認する。

### 3. Plan

対象チェックポイントの実装計画を作成し、`docs/plans/active/` に保存する。

計画には必ず以下を含める。

* チェックポイントID
* 目的
* 現状
* 制約
* 対象ファイル
* 実装方針
* 実装手順
* テスト方針
* 完了条件
* 失敗条件
* 影響範囲
* ロールバック方針
* 代替案
* 未解決事項
* 破壊的変更の有無
* ブランチ名
* 移行が必要な場合の移行手順

この計画は、別のコーダーが読んでも作業を完了できる粒度にする。

### 4. Critique

実装前に、作成した計画を必ず批判的に見直す。

以下を確認する。

* ゴールに直接近づく計画か
* 理想的なご都合主義のナラティブになっていないか
* 抜け漏れがないか
* 既存仕様を壊す可能性がないか
* テストで検知できない破壊がないか
* 変更範囲が過剰ではないか
* より単純で安全な方法がないか
* 依存関係追加の価値がコストを上回るか
* 破壊的変更をする合理性があるか
* 破壊的変更を避けた場合の不利益は明確か
* ロールバック可能か
* 将来の保守性を損なわないか
* コーダーが迷わず実装できる粒度か

問題があれば、実装前に計画を修正する。

### 5. Execute

計画に従って実装する。

実装時は以下を守る。

* 専用ブランチ上で作業する
* 対象チェックポイントに必要な変更へ集中する
* 不要なリファクタを混ぜない
* 暫定対応をした場合は理由を記録する
* 破壊的変更をした場合は影響範囲と移行方法を記録する
* エラーを隠さない
* テストを通すためだけのハードコードをしない
* 既存の未コミット変更を上書きしない

### 6. Verify

可能な範囲で確認を行う。

優先順位：

1. 既存テスト
2. 新規テスト
3. 型チェック
4. lint
5. ビルド
6. 最小動作確認
7. 回帰確認

破壊的変更を行った場合は、変更対象の主要ユースケースについて最小動作確認を行う。

実行できなかった確認がある場合は、理由を記録する。

テストが通っても、仕様と実装が整合していなければ完了扱いにしない。

### 7. Record

チェックポイント完了後、`.ai-work/state.md` を更新する。

記録する内容：

* 完了した内容
* 現在のブランチ
* 変更したファイル
* 実行した確認
* 失敗した確認
* 未実行の確認と理由
* 破壊的変更の有無
* 依存関係変更の有無
* 残った課題
* 次に処理すべきチェックポイント
* ユーザー判断が必要な事項

未完了チェックポイントがあれば `Select` に戻る。

## 完了条件

すべてのチェックポイントが完了したら、現行仕様と有効な判断を
`docs/current/`または`docs/decisions/`へ反映する。

最終報告には以下を含める。

* ゴール
* 作業ブランチ
* 達成したこと
* 変更した主なファイル
* 実行した確認
* 未実行の確認と理由
* 残った課題
* ユーザー判断が必要な事項
* 破壊的変更の有無
* 破壊的変更の理由
* 依存関係変更の有無
* 移行手順
* ロールバック方法
* 次に検討すべき事項

完了した計画書はRepo外Archiveへ複製・照合してからGit追跡を外す。
append-onlyの`docs/final-summary.md`は作成しない。


## UI / Design Rules

When changing UI, read `DESIGN.md` first.

This project is a local crypto market monitoring watchdeck, not a trading bot. UI changes must help the user find abnormal market movement, narrow candidates, verify risk/context, and retain short-lived symbol annotations. Do not add UI that implies automatic buy/sell recommendations or restores a trade lifecycle.

Rules:

* Do not introduce new colors unless they are added to `DESIGN.md`.
* Use the focus color only for selected timeframe, selected symbol, current attention, or primary UI action.
* Keep market-up, market-down, warning, data-quality, and system-state colors semantically separate.
* Do not hide stale, missing, partial, or low-quality data.
* Do not make high score, green movement, or ranking position look like a trade recommendation.
* Keep desktop density high.
* Keep mobile usable for quick review, but do not force desktop table density onto mobile.
* Treat Past Note as a 60-day symbol annotation with visible observation context, not as a trade record.
* Before changing layout, identify whether the change affects top watchdeck, symbol page, desktop, mobile, or all of them.

Validation after UI changes:

```bash
cd apps/web
bun run check
bun run test
bun run build
```

If `DESIGN.md` changes, also run:

```bash
npx -p @google/design.md designmd lint DESIGN.md
```
