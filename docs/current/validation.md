# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T22:34:31+09:00`
- 検証: `2026-09-14T22:34:31+09:00`
- 状態: `現行`

---

## 原則

変更箇所に最も近いfocused gateを先に実行する。PRで無関係なPostgres、Chromium、Web、Market Coreを毎回すべて
起動しない。`main`へのpushと明示的なfull validationでは全系統を確認する。

test green、HTTP health、単一snapshotだけをruntime/data quality/deploy/cutover完了の証拠にしない。
外部API、Postgres、Webを使う検証はproductionから隔離したdatabase、state root、port、credentialを使う。
他projectのDB/stateへ接触しない。

製品境界の正本は[`product-boundary.md`](product-boundary.md)と
[Decision 0012](../decisions/0012-product-evolution-boundary.md)。旧P0の禁止事項やqualification手順を永久的な
回帰testとして残さない。

## PR gate

`.github/workflows/verify.yml`はPRの変更pathから必要なsurfaceだけを選ぶ。

| 変更 | 実行する主なgate |
| --- | --- |
| `docs/`, root文書、`apps/scripts/config`配下のREADME、docs tooling | document contract / metadata / link |
| `apps/market-core/`, `schemas/`, Python workspace / `.python-version` | isolated Postgres + pytest + Ruff + Pyrefly |
| `apps/web/`, `schemas/` | generated types + unit + Svelte check + build |
| Webのsource/static/E2E、依存・lock・build設定、schema | desktop E2E。source内unit testだけの変更は除く |
| ops/runtime script、systemd、deploy | runtime target + install + restore safety |
| workflow、`scripts/verify-local.sh`、未分類の新しいpath | 全surface |

文書だけのPRは、入れ子のREADMEを含めてdocs gateだけを実行する。例外は明示的な全surface対象である。
全PRでmerge-baseからheadまで、pushではbeforeからheadまでの差分全体を`git diff --check`で検査する。
選択されたgateがskip/failure/cancelledなら必須`verify`を失敗させ、意図して選択しなかったgateのskipだけを許容する。

`main`へのpushは全surfaceを実行し、Web E2Eはdesktopとmobileの両方を確認する。

## Document gate

```bash
bun test \
  scripts/maintenance/document-contracts.test.mjs \
  scripts/maintenance/product-boundary.test.mjs
bun scripts/maintenance/check-document-metadata.mjs
bun scripts/maintenance/check-document-links.mjs
```

`document-contracts.test.mjs`はmetadata/link checkerの本質的な入出力だけを守る。個別edge caseを大量に固定しない。
`product-boundary.test.mjs`は新しい拡張可能な製品境界、自動executionの別Decision、旧P0 Decisionの委譲だけを守る。

## Market Core gate

```bash
cd apps/market-core
uv run pytest -q <関連test>
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
```

広いMarket Core変更、schema/migration/storage変更では全pytestと隔離Postgres integrationを実行する。
現役testはcatalog / identity / L1 / candle finality / Funding / store / artifact / selection / archive / retention等の
データ整合性とfail-closed semanticsを守る。

旧P0 shadow専用だった`run-isolated-shadow.sh`、そのtest、`capacity_sample.py`と専用testは退役済みである。
必要なcapacity/rate-limit評価は、新しいsourceやruntime変更ごとに現在のarchitectureへ合わせて設計する。

## Web gate

```bash
cd apps/web
bun run generate:types
bun test
bun run check
bun run build
```

Webのsource/static、E2E fixture、依存・lock・build設定、schemaなどbrowser behaviorへ影響する変更では、続けて
`bun run test:e2e`を実行する。通常PR E2Eはdesktop smokeを1回だけ実行する。
source内のunit testだけの変更ではunit/check/buildまでとし、E2Eは省略する。

E2Eは画面表示、検索、selection command、stale/error表示、layout破綻などbrowser境界でしか確認できない主要flowへ
限定する。テーマ個数、フォント個数、固定notional等の変更可能な現在値をE2Eで永久固定しない。

full E2E:

```bash
PREP_WATCHDECK_FULL_E2E=1 bun run test:e2e
```

fullではdesktopとmobileを実行する。CSSのsemantic roleとcontrast/accessibility testは維持する。

## Ops / runtime safety gate

```bash
bun test \
  scripts/maintenance/runtime-targets.test.mjs \
  scripts/ops/install-user-services.test.mjs \
  scripts/ops/market-postgres-restore.test.mjs
```

ここではtest DB/port隔離、service install、credential mode、production/isolated restore target等の事故防止を守る。
旧retired-record archive tool/testは現行runtimeから参照されないため退役済みである。

## Full local gate

```bash
bash scripts/verify-local.sh
```

full local gateは明示的にRepo全体を確認したい場合に使う。`TEST_DATABASE_URL`未指定なら隔離Postgres 17を一時起動する。
順序は次のとおり。

1. compact repository contract / ops safety tests
2. document metadata / link
3. workspace lock
4. Market Core全pytest / Ruff / format / Pyrefly
5. Web type generation / unit / Svelte check / build
6. desktop + mobile Playwright E2E

PRの日常gateとして無条件に`verify-local.sh`を呼ばない。

## 新しいsource / asset class / model

Stocks、新Venue、aggregator、paid/read-only API、prediction、ML、ranking、backtest等を追加する場合、既存Perp testへ
無理に押し込まずtaskごとにsource terms、identity/unit/time、freshness、storage、ranking/model definition、failure isolation、
rollbackを定義する。

## 証拠

branch、HEAD、command、exit code、実行件数、隔離target、未実行項目、runtime mutation有無を必要に応じて記録する。
変更範囲によりskipされたgateを失敗扱いしない一方、選択されたgateのfailure/timeoutを成功扱いしない。
