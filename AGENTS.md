# Prep Watchdeck Agent Guide

- 作成: `2026-06-26T16:12:22+09:00`
- 更新: `2026-08-14T22:40:28+09:00`
- 検証: `2026-08-14T22:40:28+09:00`
- 状態: `現行`

---

## Scope

`prep-watchdeck` は Bitget、Hyperliquid Core、Asterの公開crypto linear perpetualデータを扱う
local-firstの監視用monorepoである。
自動売買、注文、残高、ポジション、秘密 API key を追加しない。

- Market Core: `apps/market-core/src/prep_watchdeck_market/`
- Market Core tests: `apps/market-core/tests/`
- Database migrations: `apps/market-core/migrations/`
- Web: `apps/web/src/`
- Browser tests: `apps/web/tests/e2e/`
- Artifact schema: `schemas/`
- Service templates: `config/systemd/`
- Dedicated Postgres: `deploy/market-postgres/`
- Runtime state: `PREP_WATCHDECK_MARKET_STATE_DIR`。既定は
  `~/.local/share/prep-watchdeck-market`で、Repoの`var/`はtest用だけに使う。

runtime files、Postgres data、Parquet、`.svelte-kit`、`node_modules`、test resultsはsourceではない。

## Authoritative Documents

- architecture / process boundary: [`docs/current/architecture.md`](docs/current/architecture.md)
- schema / state / API contract: [`docs/current/data-contracts.md`](docs/current/data-contracts.md)
- UI behavior / state transition: [`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)
- runtime / service / rollback: [`docs/current/operations.md`](docs/current/operations.md)
- visual constitution: [`DESIGN.md`](DESIGN.md)
- non-trivial task plan: `docs/plans/active/<task>/`

将来予定を `docs/current/` へ現行事実として書かない。

## Core Rules

- 最初に `git status --short`、`git branch --show-current`、必要な `git diff` を確認する。
- 調査は read-only から始め、既存の未コミット変更を上書きしない。
- 依頼範囲外の API、schema、保存データ、認証、toolchain、挙動を維持する。
- 既存の設計、命名、例外処理、依存方針、test 流儀を優先する。
- 小さく可逆な変更を選び、dummy、未接続関数、不要な全面 refactor を残さない。
- 現役または他projectのPostgresへ別writerを接続しない。特にJustPassのport 5432、container、
  volume、database、roleへ接触しない。
- E2E、smoke、shadow stateとDBは現役serviceから隔離し、専用のstate root、container、portを使う。
- 課金、deploy、外部送信、秘密情報、不可逆削除、`git push` は明示指示なしに行わない。
- test green だけで runtime、データ品質、公開、受入完了まで確認済みと扱わない。

複数境界、移行、認証、互換性、高 risk、原因未確定、中断再開を伴う作業は
`docs/plans/active/<task>/` に goal、scope、checkpoint、完了条件、検証、rollback、未解決事項を
記録する。破壊的変更、依存・directory・architecture・API・type・DB schemaの変更、複数ファイルの
仕様変更では、作業前に `ai/<task-slug>-YYYYMMDD-HHMM` branch を作る。

## Toolchain and Style

- Python 3.13 と `uv` を使う。Ruff は100文字、space、double quote。test は `test_*.py`。
- JavaScript / TypeScript は `bun` を使う。Svelte component は PascalCase、unit test は
  `*.test.ts`、Playwright は `*.e2e.ts`。
- schema 由来の型は `bun run generate:types` で生成し、生成物を手編集しない。
- UI変更前に`DESIGN.md`を読み、Universe Explorer、Desktop / Mobileの影響面を特定する。

## Common Commands

```bash
bash scripts/start-all.sh
cd apps/market-core && uv run watchdeck-market migrate
cd apps/market-core && uv run watchdeck-market status
bash scripts/ops/run-market-maintenance.sh
cd apps/web && bun run generate:types
bash scripts/verify-local.sh
```

変更箇所に近い確認から実行する。

- Market Core: 関連pytest → Ruff check / format → Pyrefly。広い変更は全pytest。
- Web: `bun test` → `bun run check` → `bun run build`。interaction / route / responsive は関連 E2E。
- Docs: metadata checker、link checker、`git diff --check`。
- `DESIGN.md`: `npx -p @google/design.md designmd lint DESIGN.md`。
- Repo 横断または release: `bash scripts/verify-local.sh`。

## Completion

元の依頼、完了条件、最終 diff、実行済み検証を照合する。必須条件を証拠付きで満たした場合だけ
`PASS` とし、それ以外は `PARTIAL` または `BLOCKED` として未達と再開条件を示す。
