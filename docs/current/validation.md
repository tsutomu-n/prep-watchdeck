# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## 原則

変更箇所に最も近いfocused testから実行し、Repo横断`verify-local.sh`は最終確認で使う。

test green、HTTP health、単一snapshotだけをruntime/data quality/deploy/cutover完了の証拠にしない。

外部API、Postgres、Webを使う検証はproductionから隔離したdatabase、state root、port、credentialを使う。
他projectのDB/stateへ接触しない。

製品境界の正本は[`product-boundary.md`](product-boundary.md)と
[Decision 0012](../decisions/0012-product-evolution-boundary.md)。
旧P0の禁止事項を回帰testとして永久固定しない。

## Product-boundary gate

```bash
bun test scripts/maintenance/product-boundary.test.mjs
```

このtestは次を確認する。

- ranking、Stocks、paid market data、ML、backtest、Decision Memo / Trade Journal等が製品境界内である
- 自動注文、資金移動、無人executionは別Decisionが必要である
- 現在のtimeframe、bar数、artifact数等を永久制約にしない
- AGENTSが新product boundaryを旧P0文書より優先する
- P0 Scope Freezeが終了済みbaselineとして扱われる
- Decision 0011が将来product scopeをDecision 0012へ委譲する

旧`monitoring-only-boundary.test.mjs`のように、Trade Memo、Weekly Review、Pre-Trade等のfeature名そのものを
production codeから禁止しない。

## Market Core focused gate

```bash
cd apps/market-core
uv run pytest -q <関連test>
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
```

現在のPerp runtime変更では、変更箇所に応じて次を確認する。

- catalog / identity / provenance
- L1 / candle / freshness / no stale reuse
- settled funding / version boundary / conflict guard
- selected market / cleanup / TTL / depth/trade
- artifact schema / atomic write / invalid numeric
- archive / readback / checksum / retention

現在の20秒fetch、50秒deadline、48時間Funding catch-up、1 selection、20 depth、100 trades等は現行実装値。
変更時はtestとcapacity/rate-limit検証を更新できる。

## 新しいsource / asset class / model

Stocks、新Venue、aggregator、paid/read-only API、prediction、ML、ranking、backtest等を追加する場合、既存Perp gateへ
無理に押し込まず、次をtaskごとに定義する。

- source terms / rate limits / auth scope
- identity / unit / timestamp / timezone
- freshness / missing / correction semantics
- storage / retention / capacity
- ranking/model feature definitionとversion
- leakage / lookahead / survivorship等のbacktest risk
- failure isolation
- rollback

credential付きread-only APIを使うこと自体を失敗条件にしない。write/trading scopeが混入していないかを確認する。

## Web focused gate

```bash
cd apps/web
bun run generate:types
bun test
bun run check
bun run build
```

route、interaction、selection、ranking、Chart、responsive等を変えた場合は関連Playwrightを実行する。

1440px / 390pxは現在の主要visual check例であり永久の唯一targetではない。Desktopとnarrow viewportの双方で主要flowを
確認する。

## Docs / Ops focused gate

```bash
bun test \
  scripts/maintenance/document-metadata.test.mjs \
  scripts/maintenance/document-links.test.mjs \
  scripts/maintenance/product-boundary.test.mjs \
  scripts/maintenance/web-port.test.mjs \
  scripts/ops/install-user-services.test.mjs \
  scripts/ops/market-postgres-restore.test.mjs \
  scripts/ops/run-isolated-shadow.test.mjs

bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
git diff --check
```

ops testは実user unit、production container/database、他project資源へ接触しない。

## Full local gate

```bash
bash scripts/verify-local.sh
```

`TEST_DATABASE_URL`が未指定の場合、現行scriptは隔離Postgres 17を一時起動してintegration testを実行する。
指定する場合もisolated test DBに限定する。

現在のfull gate順序:

1. maintenance / ops / product-boundary tests
2. document metadata / link
3. workspace lock
4. market-core pytest / Ruff / format / Pyrefly
5. Web type generation / unit / Svelte check / build
6. Playwright E2E

未実行、skip、timeout、既存失敗を成功扱いしない。

## Runtime smoke / shadow

現行3 Venue Perp runtimeを変更する場合、必要に応じてisolated smoke/shadowでcatalog、L1、candle、Funding、DB、
artifact、selected subscription、capacity、429、resource usageを確認する。

旧P0 cutover時の15分baseline / 60分shadow、旧DuckDB writer、旧snapshot比較等は当時のqualification methodであり、
すべての将来featureへ固定適用しない。現在の変更riskに合った受入時間・metricをplanで定義する。

production既定port/state、JustPass等の他project資源、live runtimeへ無断で接触しない原則は維持する。

## 証拠

branch、HEAD、既存差分、時刻、command、exit code、隔離target、実行件数、未実行項目、runtime mutation有無、
rollbackを必要に応じて記録する。credential、raw secretを証拠へ残さない。

実装、focused gate、必要なintegration/runtime validation、最終diffのmandatory条件が満たされた場合だけPASSとする。
push、merge、deploy、cutoverはそれぞれ別の状態として扱う。
