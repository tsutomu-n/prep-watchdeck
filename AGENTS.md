# Prep Watchdeck Agent Guide

- 作成: `2026-06-26T16:12:22+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## Product Boundary

`prep-watchdeck`は、裁量トレーダーが市場から注目対象を発見し、分析し、比較し、最終判断を行うための
local-first market intelligence workspaceである。

現行productionはBitget、Hyperliquid Core、Asterのpublic crypto linear perpetualを扱うPerp Universe
Explorerだが、この3 Venue、asset class、データ源、UI、ranking、Chart、保存期間、selection数等を
将来の永久制約として扱わない。

最初に[`docs/current/product-boundary.md`](docs/current/product-boundary.md)と
[`docs/decisions/0012-product-evolution-boundary.md`](docs/decisions/0012-product-evolution-boundary.md)を読む。
旧P0のscope freeze、ranking禁止、新Venue/aggregator禁止、Stocks/RWA禁止、paid/read-only API禁止、
ML/backtest禁止、trade-support identifier禁止、固定timeframe/bar数等は将来機能を拒否する根拠にしない。

現在未実装の機能は`未実装`と`禁止`を区別する。既存code/schemaが3 Venue Perpへ特化している場合、
必要に応じて新しいbounded context、app、artifact、schema、routeとして追加し、無理な汎用化をしない。

自動注文、資金移動、無人executionは現在の既定責務外。導入する場合はsecurity、権限、kill switch、audit、
rollbackを扱う新しいDecisionが必要である。ranking、score、prediction、方向評価、read-only account data、
Decision Memo / Trade Journal自体は禁止しない。

## Repository Scope

- Market Core: `apps/market-core/src/prep_watchdeck_market/`
- Market Core tests: `apps/market-core/tests/`
- Database migrations: `apps/market-core/migrations/`
- Web: `apps/web/src/`
- Browser tests: `apps/web/tests/e2e/`
- Artifact schema: `schemas/`
- Service templates: `config/systemd/`
- Dedicated Postgres: `deploy/market-postgres/`
- Runtime state: `PREP_WATCHDECK_MARKET_STATE_DIR`。現行既定は
  `~/.local/share/prep-watchdeck-market`。

runtime files、Postgres data、Parquet、`.svelte-kit`、`node_modules`、test resultsはsourceではない。

## Authoritative Documents

製品境界と将来拡張の判断は次を優先する。

1. [`docs/current/product-boundary.md`](docs/current/product-boundary.md)
2. [`docs/decisions/0012-product-evolution-boundary.md`](docs/decisions/0012-product-evolution-boundary.md)
3. 現行code、schema、migration、tests、CLI help
4. その他の`docs/current/`
5. 現行runtimeのarchitecture baselineとしてDecision 0011

個別の現行runtime仕様:

- user-facing usage: [`docs/current/user-manual.md`](docs/current/user-manual.md)
- architecture: [`docs/current/architecture.md`](docs/current/architecture.md)
- schema / state / API: [`docs/current/data-contracts.md`](docs/current/data-contracts.md)
- UI behavior: [`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)
- runtime / rollback: [`docs/current/operations.md`](docs/current/operations.md)
- validation: [`docs/current/validation.md`](docs/current/validation.md)
- visual defaults and UX principles: [`DESIGN.md`](DESIGN.md)
- non-trivial task plan: `docs/plans/active/<task>/`

現在値と製品境界を混同しない。例えば`5m/15m/1h/4h/24h`、500 bars、1 selection、20 depth、
100 trades、4 artifacts、retention日数、localhost port等は現行実装値であり変更可能である。

## Core Rules

- 最初に `git status --short`、`git branch --show-current`、必要な `git diff` を確認する。
- 調査はread-onlyから始め、既存の未コミット変更を上書きしない。
- 依頼範囲外のAPI、schema、保存データ、認証、toolchain、挙動を不用意に変更しない。
- 既存の設計、命名、例外処理、依存方針、test流儀を尊重するが、旧scope freezeを永久規制として維持しない。
- 小さく可逆な変更を選び、dummy、未接続関数、不要な全面refactorを残さない。
- 現役または他projectのPostgresへ別writerを接続しない。特にJustPassのport 5432、container、volume、
  database、roleへ接触しない。
- E2E、smoke、shadow stateとDBは現役serviceから隔離する。
- stale、missing、partial、invalidを0、前回値、推測値で埋めない。
- source、時刻、単位、finality、identity、quality、provenanceを失わない。
- symbol名だけからalias、multiplier、cross-market identityを推測して同一視しない。
- secretをGit、artifact、log、issue、文書へ残さない。
- test greenだけでruntime、data quality、deploy、cutoverまで完了扱いしない。
- 明示承認なしにcommit、push、PR、merge、unit install/start/stop/restart、live DB migration、deploy、
  cutover、不可逆削除を行わない。

複数境界、移行、認証、互換性、高risk、原因未確定、中断再開を伴う作業は
`docs/plans/active/<task>/`にgoal、scope、checkpoint、完了条件、検証、rollback、未解決事項を記録する。
破壊的変更、依存・directory・architecture・API・type・DB schemaの変更、複数ファイルの仕様変更では、
作業前に`ai/<task-slug>-YYYYMMDD-HHMM` branchを作る。

Plan完了・中止・置換時は、現行事実を`docs/current/`、採用済み判断を`docs/decisions/`へ反映してから
active planを削除する。過去planはGit履歴で参照する。

## Toolchain and Style

- Python 3.13と`uv`。Ruffは100文字、space、double quote。testは`test_*.py`。
- JavaScript / TypeScriptは`bun`。Svelte componentはPascalCase、unit testは`*.test.ts`、
  Playwrightは`*.e2e.ts`。
- schema由来型は`bun run generate:types`で生成し、生成物を手編集しない。
- UI変更前に`DESIGN.md`を読む。ただしvisualの現在値を永久禁止と解釈せず、accessibility、state semantics、
  data integrityを優先する。

## Common Commands

### Read-only status

```bash
git status --short
git diff
cd apps/market-core && uv run watchdeck-market status
bash scripts/update-live.sh
```

`update-live.sh`は収集を実行せず、現在のartifact状態を読む。

### State-changing or output-generating

```bash
bash scripts/start-all.sh
cd apps/market-core && uv run watchdeck-market migrate
bash scripts/ops/run-market-maintenance.sh
cd apps/web && bun run generate:types
bash scripts/verify-local.sh
```

変更箇所に近い確認から実行する。

- Market Core: 関連pytest → Ruff check / format → Pyrefly。広い変更は全pytest。
- Web: `bun test` → `bun run check` → `bun run build`。interaction / route / responsiveは関連E2E。
- Docs: metadata checker、link checker、`git diff --check`。
- `DESIGN.md`: design lintが現行toolchainに含まれる場合は実行する。
- Repo横断またはrelease: `bash scripts/verify-local.sh`。

## Completion

元の依頼、完了条件、最終diff、実行済み検証を照合する。必須条件を証拠付きで満たした場合だけ`PASS`。
未達があれば`PARTIAL`または`BLOCKED`として、未達項目と再開条件を示す。
