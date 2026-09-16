# prep-watchdeck 現行検証

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
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
| `apps/ranking-core/`, `scripts/ranking/`, ranking schema、Python workspace | ranking pytest / Ruff / Pyrefly / schema / map資格 |
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
bun run test
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
5. Ranking Core全pytest / Ruff / format / Pyrefly / schema / map根拠とランキング資格
6. Web type generation / unit / Svelte check / build
7. desktop + mobile Playwright E2E

PRの日常gateとして無条件に`verify-local.sh`を呼ばない。

## 新しいsource / asset class / model

Stocks、新Venue、aggregator、paid/read-only API、prediction、ML、ranking、backtest等を追加する場合、既存Perp testへ
無理に押し込まずtaskごとにsource terms、identity/unit/time、freshness、storage、ranking/model definition、failure isolation、
rollbackを定義する。

## 証拠

branch、HEAD、command、exit code、実行件数、隔離target、未実行項目、runtime mutation有無を必要に応じて記録する。
変更範囲によりskipされたgateを失敗扱いしない一方、選択されたgateのfailure/timeoutを成功扱いしない。

## ChartとJST基準騰落率の検証

Chart履歴はprovider/route unitで、銘柄の解決、native時間足、UTC境界、数値検証、排他的な
pagination、cache・timeout・Bitgetの取得間隔を確認する。E2Eは履歴APIをfixtureへ隔離し、
時間足の保持、定期更新後のズーム保持、古い応答の排除、JST表示、過去追加時の表示範囲を確認する。
接続確認では公開銘柄だけを使い、最新ページと過去ページのOHLC・日時・重複・ページ境界を照合する。
実APIの有限canary成功は、全銘柄・継続運転・本番反映の受入とは区別する。

約定騰落率は任意HH:mmのJST日次境界、基準足の完全一致、最新価格の鮮度、同じ契約versionの
価格同士の計算と、分境界をまたいだ取得中要求を新しい基準へ共有しないことをunit/APIで確認する。
Browser側は同時取得数、可視対象、非表示tab、設定・日付・
version変更後の古い応答排除、保存失敗を確認する。E2Eでは騰落率APIもfixtureへ隔離し、設定の変更・
保存・再読込、日次切替、欠測の理由表示をDesktop/Mobileで検証する。

## 独立ランキングの検証

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyrefly check
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117
uv run --package prep-watchdeck-ranking python scripts/ranking/generate-schema.py --check
uv run --package prep-watchdeck-ranking python scripts/ranking/verify-map-evidence.py
uv run watchdeck-ranking validate-map apps/ranking-core/data/initial-map.json --require-ranking-qualified
```

最後のcommandは原資産同一性・固定参照契約の全件照合gateであり、行の要確認が残る間は終了code 1になる。
/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/verify-local.sh にも組み込み、未照合のままfull gateを成功させない。
元数量倍率・Widgetの未確認は件数と機能への影響を独立して報告する。両方も確認済みであることを
要求する旧`--require-reviewed`は維持し、未確認が残る間は終了1とする。
map根拠整合commandの成功、`rankingQualified`、`qualificationComplete`、実データ受入を区別する。
全件照合gateで停止した後にWebを個別検証しても、full gateの終了結果は失敗のまま記録する。
要確認の件数・理由は /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core/data/README.md を参照する。

計算では確定終値、同じ期間のquote売買代金、欠測、実0、JST日跨ぎ・任意分基準、古い要求、後着訂正、
immutable generationを検証する。Providerの不正な応答構造は検証エラーとして扱い、収集の再接続と
補完workerの継続を確認する。RESTはcatalog取得も含めて各Provider同時2接続以内とする。
Webでは期間・方向・下限・保存失敗、選択のID保持、遅れて返る旧要求を確認する。
mapから削除された選択については、その後の期間・並び順・下限変更で応答が遅延・失敗しても
旧Widgetが復活しないこと、新しく選んだ有効銘柄のWidgetを表示できることを確認する。

実Providerの有限受入は
[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/ranking/accept-live.py](../../scripts/ranking/accept-live.py)
を専用state・別port・OS書込み制限下で実行する。全対応数について15分・1時間・JST基準の
3連続世代、12条件の読取りと外部取得量の分離、実WS切断・再接続、75秒の収集停止と再開を記録する。
時間上限は900秒。原stateを隠した試験と、専用state外の書込みが拒否された証拠も別に残す。
map versionと対応範囲を受入証拠へ結び付け、異なるmapでの全件成功を新mapの全件受入へ流用しない。
実Widgetの追加銘柄が表示できても、追加後mapの全Provider取得・連続更新の受入とは区別する。

[/home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/scripts/ranking/verify-live-values.py](../../scripts/ranking/verify-live-values.py)
は同じTの実API応答を独立したDecimal計算で照合する。`--port`の代わりに`--snapshot`で
有限受入が保存した全期間の同一世代を指定でき、`--asset`の繰り返しで追加の必須対象を選べる。
元数量未確認の新規採用行も指定し、同じ参照のREST足と4指標を照合する。
Widgetの通常E2Eはfixtureへ隔離し、
実Widgetは契約種別・倍率・文字種・Desktop/Mobile・URL指定・検索・比較を別途確認する。
銘柄名だけでなく足・価格の描画を実画像で確認し、公開した全契約を実表示した証拠とは混同しない。

## 日常利用の追加指標と再開受入

順位変化は、直前の発行済み世代・同条件の再計算・同順位・新規・現在順位外・欠落・再起動・
map/指標変更・JST基準切替・後着訂正を検証する。直近24時間内の同期間中央値との比較は
最新窓除外・95窓/23窓・0・基準0・1本の欠測を、当日高安位置はhigh/lowと終値の違い・
JST 00:00・値幅0・範囲外入力を手計算fixtureで照合する。新指標の欠測で既存順位を変えない。

Gitの除外設定によりPyreflyのproject検査が未追跡testsを省略する作業先では、対象fileを明示して
検査した結果も残す。現在のランキングmoduleの補完commandは次のとおり。

```bash
cd /home/tn/projects/prep-watchdeck/.ai-work/ranking-chart-release-20260916-2117/apps/ranking-core
uv run pyrefly check --config pyproject.toml --use-ignore-files=false src/prep_watchdeck_ranking/*.py tests/*.py
```

有限helperの`--prepare-only`は空の専用stateの履歴準備と通常3連続世代だけを確認する。
全対応契約について既存3期間に加え、15分/1時間の平常比とJST当日高安位置の入力がそろうことを
検査する。各指標のstatus内訳、順位変化のstatus、除外理由、共通T、処理時間、RSS、Provider取得数を
世代ごとに残す。各実行は最大900秒を維持し、成功した準備証拠はpreparation.jsonへ出力する。

復旧は`--prepare-only`なしの別実行とし、通常3連続世代、12条件読取り、実WS切断・再接続、
75秒停止、保存済みstateから再開後3連続世代をacceptance.jsonへ記録する。初回と再開時に
比較元の世代がないこと、その後の世代が同条件で比較可能なことも確認する。空state受入を
保存済みstateからの試験で置き換えない。source hash/map/実行時刻と隔離証拠を各実行へ結び付ける。

実API照合helperは、代表Bybit/Binance契約と対応する数量倍率契約について同じTの24時間確定足を
独立したDecimal計算で比較する。既存の騰落率・売買代金と新しい中央値比・high/low位置を照合し、
元API応答・入力窓・中央値・高値・安値・終値・差を保存する。これも全契約の実値照合とは区別する。

Desktop/Mobileでは実レスポンスと表示値、設定変更、選択保持、初回・更新停止の理由、
Widgetの契約・足・価格描画を確認する。fixtureのWidgetと実TradingView受入の記録は分離する。
