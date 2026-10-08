# Prep Watchdeck Agent Guide

timestamp="2026-10-09(金)_00:39 JST"
- 作成: `2026-06-26T16:12:22+09:00`
- 更新: `2026-10-09T00:39:16+09:00`
- 検証: `2026-09-29T20:39:32+09:00`
- 状態: `現行`

---

## 製品境界

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

## 対象範囲

以下の相対pathとcommandはRepo root基準。package内で実行するcommandは作業directoryを明示する。

- Market Core: `apps/market-core/src/prep_watchdeck_market/`
- Market Core tests: `apps/market-core/tests/`
- Database migrations: `apps/market-core/migrations/`
- Ranking Core / tests: `apps/ranking-core/src/prep_watchdeck_ranking/`、`apps/ranking-core/tests/`
- Ranking map / evidence: `apps/ranking-core/data/`
- Ranking検証・隔離実行: `scripts/ranking/`
- Attention Core / tests: `apps/attention-core/src/prep_watchdeck_attention/`、`apps/attention-core/tests/`
- Attention schema / isolation: `scripts/attention/`、`schemas/attention-*.schema.json`
- Web: `apps/web/src/`
- Browser tests: `apps/web/tests/e2e/`
- Artifact schema: `schemas/`
- Service templates: `config/systemd/`
- Dedicated Postgres: `deploy/market-postgres/`
- Market runtime state: `PREP_WATCHDECK_MARKET_STATE_DIR`。既定は
  `~/.local/share/prep-watchdeck-market`で、Repoの`var/`はtest用だけに使う。
- Attention runtime state: `PREP_WATCHDECK_ATTENTION_STATE_DIR`。既定は
  `~/.local/share/prep-watchdeck-attention`。Market/Ranking stateとの同一・包含・被包含とrepo var、symlinkを拒否する。
- Ranking runtime state: `PREP_WATCHDECK_RANKING_STATE_DIR`。既定は
  `~/.local/share/prep-watchdeck-ranking`。Market stateと同一・内包関係のdirectoryを使わない。

runtime files、Postgres / Ranking SQLite data、Parquet、`.svelte-kit`、`node_modules`、
test resultsはsourceではない。Rankingのmap・名簿・根拠JSONは管理対象であり、runtime dataと区別する。

## 正本ドキュメント

製品境界と将来拡張の判断は次を優先する。

1. [`docs/current/product-boundary.md`](docs/current/product-boundary.md)
2. [`docs/decisions/0012-product-evolution-boundary.md`](docs/decisions/0012-product-evolution-boundary.md)
3. 現行code、schema、migration、tests、CLI help
4. その他の`docs/current/`
5. 現行runtimeのarchitecture baselineとしてDecision 0011

個別の現行runtime仕様:

- user-facing usage / interpretation: [`docs/current/user-manual.md`](docs/current/user-manual.md)
- architecture / process boundary: [`docs/current/architecture.md`](docs/current/architecture.md)
- schema / state / API contract: [`docs/current/data-contracts.md`](docs/current/data-contracts.md)
- UI behavior / state transition: [`docs/current/ui-workflow.md`](docs/current/ui-workflow.md)
- runtime / service / rollback: [`docs/current/operations.md`](docs/current/operations.md)
- 検証 / 受入境界: [`docs/current/validation.md`](docs/current/validation.md)
- 文書更新規則: [`docs/current/documentation.md`](docs/current/documentation.md)
- 独立ランキングの設計判断: [`docs/decisions/0013-independent-ranking.md`](docs/decisions/0013-independent-ranking.md)
- visual constitution: [`DESIGN.md`](DESIGN.md)
- non-trivial task plan: `docs/plans/active/<task>/`

現在値と製品境界を混同しない。例えば`5m/15m/1h/4h/24h`、500 bars、1 selection、20 depth、
100 trades、4 artifacts、retention日数、localhost port等は現行実装値であり変更可能である。

将来予定を `docs/current/` へ現行事実として書かない。
`docs/current/`はRepositoryの現行仕様であり、commit、push、merge、live cutover、現在hostで稼働中の
versionとは別の状態である。`docs/plans/active/`には未完了作業のplanだけを置き、[docs index](docs/README.md)
からリンクされたplanだけを候補としてcodeと現在差分へ照合する。

Attentionは既存Market artifactとRanking loopback APIだけを読む。Provider取得、Market/Ranking writer、manual selection、actual captureを追加しない。隔離runnerはLinux bubblewrapを必須とし、production配置・capacity・30日evidenceは別受入である。

## 作業規則

- 最初に `git status --short`、`git branch --show-current`、必要な `git diff` を確認する。
- 別worktreeの実装や保管用branchを、現在のcheckoutや稼働中releaseと同一視しない。
- 調査は read-only から始め、既存の未コミット変更を上書きしない。
- 依頼範囲外の API、schema、保存データ、認証、toolchain、挙動を維持する。
- 既存の設計、命名、例外処理、依存方針、test 流儀を優先するが、旧scope freezeを永久規制として維持しない。
- 小さく可逆な変更を選び、dummy、未接続関数、不要な全面 refactor を残さない。
- 現役または他projectのPostgresへ別writerを接続しない。特にJustPassのport 5432、container、
  volume、database、roleへ接触しない。
- E2E、smoke、shadow stateとDBは現役serviceから隔離し、専用のstate root、container、portを使う。
- stale、missing、partial、invalidを0、前回値、推測値で埋めない。
- source、時刻、単位、finality、identity、quality、provenanceを失わない。
- symbol名だけからalias、multiplier、cross-market identityを推測して同一視しない。
- secretをGit、artifact、log、issue、文書へ残さない。
- Rankingの価格・売買代金を元の3 Venueの値で補完しない。Market CoreのPostgres・Parquet・
  artifactへRankingから書き込まず、TradingView Widgetは表示専用とする。
- 明示承認なしにunitのinstall / enable / start / stop / restart、live DB
  migration、maintenance、backup、restore、deploy、cutover、旧state削除を行わない。
- 課金、外部送信、秘密情報の変更、不可逆削除は明示指示なしに行わない。
- test green だけで runtime、データ品質、公開、受入完了まで確認済みと扱わない。
- PR作成は行わない。
- 変更完了後は、禁止されていなければ必要な検証後に今回の差分だけをstageしてcommitする。
  対象外のstaged / 未commit差分は保全し、安全に分離できなければcommitだけを保留する。
  push / mergeは今回のユーザーが操作と対象を明示した場合だけ実行する。

複数境界、移行、認証、互換性、高 risk、原因未確定、中断再開を伴う作業は
`docs/plans/active/<task>/` に goal、scope、checkpoint、完了条件、検証、rollback、未解決事項を
記録する。破壊的変更、依存・directory・architecture・API・type・DB schemaの変更、複数ファイルの
仕様変更では、作業前に `ai/<task-slug>-YYYYMMDD-HHMM` branch を作る。

Planが完了、中止、または別の判断により置換された場合は、現行事実を`docs/current/`、採用済み判断を
`docs/decisions/`へ反映してから、そのplanを現行treeから削除する。過去planはGit履歴で参照する。

## ツールと記法

- Python 3.13 と `uv` を使う。Ruff は100文字、space、double quote。test は `test_*.py`。
- JavaScript / TypeScript は `bun` を使う。Svelte component は PascalCase、unit test は
  `*.test.ts`、Playwright は `*.e2e.ts`。
- schema 由来の型は `bun run generate:types` で生成し、生成物を手編集しない。
- Ranking schemaは `apps/ranking-core/src/prep_watchdeck_ranking/models.py` を正本とし、
  Repo rootで `uv run --package prep-watchdeck-ranking python scripts/ranking/generate-schema.py`
  を実行してから、`apps/web/`で `bun run generate:types` を実行する。
- `uv.lock`、`apps/web/bun.lock`、schema、`apps/web/src/lib/generated/`の型は管理対象。
  `.gitignore`で隠さず、再生成差分を確認する。
- UI変更前に`DESIGN.md`を読み、Markets、Universe Explorer、ランキング、Desktop / Mobileの影響面を特定する。
  visualの現在値を永久禁止と解釈せず、accessibility、state semantics、data integrityを優先する。

## よく使うコマンド

### 収集・運用stateを変更しない確認

```bash
git status --short
git diff
(cd apps/market-core && uv run --no-sync watchdeck-market status)
bash scripts/update-live.sh
```

CLIは依存の準備済み環境で実行し、`status`には専用DBの接続設定が必要。
`update-live.sh`は起動済みのloopback Webの`/api/market-data`からartifact状態を読む。
どちらもserviceを起動せず、migrationや収集を実行しない。

### state変更・生成物を伴う操作

```bash
bash scripts/start-all.sh
(cd apps/market-core && uv run watchdeck-market migrate)
bash scripts/ops/run-market-maintenance.sh
(cd apps/web && bun run generate:types)
bash scripts/verify-local.sh
```

`start-all.sh`、`migrate`、maintenanceはlocal stateを変更する。`verify-local.sh`は一時Postgres、
type生成、build、Playwrightを実行する。`generate:types`と`verify-local.sh`は生成物やtest出力を作る。
いずれもread-only調査の確認commandとして実行しない。

### 変更に応じた検証

変更箇所に近い確認から実行する。文書・ignore規則だけの変更で全体gateを機械的に実行しない。

- Market Core / Ranking Core / Attention Core: 各packageで関連pytest → Ruff check / format --check → Pyrefly。
  広い変更は当該packageの全pytest。
- Rankingのmodel・map・根拠を変更した場合は、Repo rootで次も実行する。

  ```bash
  uv run --package prep-watchdeck-ranking python scripts/ranking/generate-schema.py --check
  uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py
  uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-reviewed
  ```

- Attention schema変更時はRepo rootで`uv run --package prep-watchdeck-attention python scripts/attention/generate-schema.py --check`も実行する。
- Web: `apps/web/`で `bun run test`（Vitest）→ `bun run check` → `bun run build`。
  interaction / route / responsive は関連 E2E。Repoのmaintenance用 `bun test` と区別する。
- Docs: Repo rootで次を実行する。対象文書を引数に指定すると局所確認できる。

  ```bash
  bun scripts/maintenance/check-document-metadata.mjs
  bun scripts/maintenance/check-document-links.mjs
  git diff --check
  ```

- ignore規則: `git check-ignore -v --no-index -- <path>` でruntime・秘密設定の除外と、
  template・fixture・map・schema・lockfileの非除外を確認する。出力の`!`は非除外を表す。
  `git ls-files -ci --exclude-standard` で管理対象との衝突を確認する。
  `.gitignore`の追加は既存の追跡を解除しない。自動で `git rm --cached` を実行しない。
- `DESIGN.md`: `npx -p @google/design.md designmd lint DESIGN.md`。
- Repo 横断または release: `bash scripts/verify-local.sh`。

## 完了判定

元の依頼、完了条件、最終 diff、実行済み検証を照合する。必須条件を証拠付きで満たした場合だけ
`PASS` とし、それ以外は `PARTIAL` または `BLOCKED` として未達と再開条件を示す。
source検証、commit、push、稼働反映、実データ受入はそれぞれ別に報告する。
