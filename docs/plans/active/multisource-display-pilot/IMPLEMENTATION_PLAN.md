# ExecPlan: 3市場mark price表示pilot

- 作成: `2026-08-11T19:48:00+09:00`
- 更新: `2026-08-11T20:14:15+09:00`
- 状態: `実装計画`
- Plan ID: `2026-08-11-multisource-display-pilot`
- Profile / risk: `EXECPLAN / MEDIUM`
- Base revision: `953589b744cc083fb41c7e2845fb5ac4517b68cd`
- Current checkpoint: `CP-05 complete`

## 0. 結論と現在地

- **Target**: Bitget・Hyperliquid・BybitのBTC/ETH/SOL mark priceを5分RESTで比較し、raw値、鮮度、coverage、spread、3/3時だけのmedianを選択銘柄detailへ表示する。
- **現在地**: 3社取得、3/3集約、optional snapshot sidecar、Selected detail表示まで実装済み。focused test、check、build、live API smoke、system ChromeによるE2Eは成功した。
- **次の行動**: implementation checkpoint外のdeliveryとしてcommit/pushとcontrolled restartを行う。24時間観測は任意の後続作業とする。
- **最大のRisk / Blocker**: HyperliquidのUSD建てと2社のUSDT建ては完全同一ではない。UIでは参考値と明示し、rankingや売買判定には使わない。

## 1. 作業契約

### Objective

- Bitget単独値だけでは見えないvenue乖離が、監視判断に有用かを最小pilotで検証する。
- 新規市場clientを自作・追加せず、現行で固定済みの`pybotters 1.11.2`を再利用する。

### Target

- 対象はBTC、ETH、SOLだけ。
- 取得元はBitget USDT perpetual、Hyperliquid perpetual、Bybit linear perpetualだけ。
- 取得はpublic REST、周期は300秒。WebSocket、長期履歴、DB永続化は追加しない。
- 各sourceのmark price、source識別子、symbol、quote表現、observedAt、nullableなsourceAtを保持する。
- 同一refresh cycleの3sourceが全てfreshかつ正数のときだけmedianとspreadを計算する。
- optional Cold snapshot sidecarとして公開し、選択銘柄detailでだけ表示する。

### Preserve

- Candidate、Watchlist、Raw Sort、Smart Rank、VPI-Lite+、74h/OI、category、Hot ticker、chartの意味と更新経路。
- snapshot schema version、既存required field、DuckDB schema、active state layout、single writer。
- public data only、監視専用、注文・残高・position・秘密情報なしの製品境界。
- Bitget障害処理、service shutdown、reconcile/deep backfill、既存依存version。

### Non-goals / Deferred

- TradingViewからの自動取得、非公式TradingView API、screen scraping。
- 全銘柄化、共通universe自動生成、WebSocket化、1秒更新。
- OI、funding、volume、OHLCのmedian。
- composite値によるranking、filter、Candidate、通知、売買判断。
- `ccxt`、Hyperliquid公式SDK、`pybit`、`cryptofeed`のproduction依存追加。

### Acceptance criteria

| ID | Mandatory | Condition | Source | Verification | Status | Evidence |
|---|---:|---|---|---|---|---|
| AC-01 | yes | BTC/ETH/SOLについて3社のperpetual mark priceとsymbol mappingがread-only probeで確認できる | user / unresolved | captured public response shape | verified | 2026-08-11 live probeで9値取得 |
| AC-02 | yes | 既存`pybotters 1.11.2`以外のdependency、private API、注文、WebSocketを追加しない | user / repo | final diff、lockfile diffなし | verified | dependency/lockfile変更なし |
| AC-03 | yes | 5分周期の失敗がsource単位で閉じ、Bitget scanner、Cold snapshot、serviceを停止させない | default / repo | focused Python tests、code inspection | verified | collectorは例外を欠損blockへ変換 |
| AC-04 | yes | median/spreadは同一cycleのfreshな3/3正数値だけで生成し、2/3以下ではnullになる | user / default | pure unit tests | verified | `test_market_comparison.py` 2 passed |
| AC-05 | yes | sidecarはoptionalで、既存ranking、rows、category、VPI、Hot ticker、chartを変更しない | repo | snapshot regression test、final diff | verified | optional injection test passed |
| AC-06 | yes | Dashboard detailにraw値、source、quote、時刻、coverage、spread、medianまたは明示的欠損理由を表示する | user | parser unit、build、browser smoke | verified | parser/check/buildとsystem Chrome E2E成功 |
| AC-07 | yes | DB schema、snapshot required schema、state layout、systemd unitを変更しない | repo / default | final diff | verified | 対象fileに変更なし |
| AC-08 | yes | focused tests、Web check/build、live collector smoke、docs/diff checkが成功する | repo | recorded commands and exit codes | verified | Python 50、Web 227、E2E 1、check/build/docs/diff成功 |
| AC-09 | no | 24時間または288 cycleの隔離観測でcoverage、age、spreadを記録する | follow-up | qualification artifact summary | deferred | runnable化後に価値判断が必要な場合だけ行う |

## 2. 現状と判断

### Facts

| ID | Fact | Evidence |
|---|---|---|
| F-01 | scanner-coreだけが外部market data取得を担当し、Webはlocal artifactを読む | `docs/current/architecture.md` |
| F-02 | 現行Bitget REST clientは`pybotters.Client`を利用し、lockは`pybotters 1.11.2` | `bitget/client.py`、`uv.lock` |
| F-03 | pybotters 1.11.2にはBitget・Bybit・HyperliquidのHTTP/WS対応、DataStore model、exampleがある | upstream README/source、2026-08-11確認 |
| F-04 | snapshot `summary`はadditional propertiesを許し、VPIもoptional sidecarを局所parserで扱う | schema、`service_snapshot.py`、`vpi-lite-plus.ts` |
| F-05 | `lightweight-charts 5.2.0`は既に導入済みだが、本pilotはチャート系列を増やさない | `apps/web/package.json`、`MarketChart.svelte` |
| F-06 | TradingViewは市場データ取得APIではなく、非公式取得は今回のsourceにしない | 2026-08-11の一次仕様確認とユーザー承認 |

### Material assumptions / unknowns

| ID | Type | Content | Impact if wrong | Resolution / Revisit |
|---|---|---|---|---|
| A-01 | assumption | 5分更新で人間の監視用途に十分 | 1分未満の価値が必須ならpilot設計が不足 | pilot利用後に別判断。今回は短縮しない |
| A-02 | unknown | 三社のmark priceとquote表現が直接比較できる | medianを公開できない | CP-01で実測。曖昧なら停止 |
| A-03 | unknown | Hyperliquid payloadに信頼できるsource timestampがある | observedAtしか表示できない | sourceAtをnullableにし、時刻を偽造しない |
| A-04 | assumption | BTC/ETH/SOLでvenue乖離の表示価値を判定できる | altcoin固有の価値を見落とす | pilot成功後だけ対象拡張を再審査 |

### Selected approach

- **Decision**: 既存pybottersによる独立5分REST collectorのin-memory結果を、VPIと同様のoptional Cold sidecarとして渡す。
- **Reason**: 新規dependency、DB migration、別writer、外部APIをWebへ持ち込まず、既存scanner判定から切り離せる。
- **Alternatives**: CCXT全面移行は既存Bitget取得の再検証範囲が大きい。Webから直接fetchはprocess境界違反。別artifact/APIはsidecarよりsurfaceが増える。いずれも不採用。

## 3. Checkpoints

### CP-01: Public contract probe

- **Status**: completed
- **Goal**: 3銘柄×3sourceのmark price、contract、quote、timestamp、symbol mappingを確定する。
- **Linked ACs**: AC-01、AC-02
- **Dependencies**: public endpointsへのnetwork access。
- **Targets**: source docs、read-only probe output。repo code変更なし。
- **Work**: response shapeと値の意味を一次仕様と実応答で照合する。
- **Preserve / Do not change**: API keyを使わない。現役service/DBへ接続しない。
- **Completion criteria**: comparison tableに曖昧な必須fieldがない。
- **Verification**: 3社各endpointを一回以上取得し、symbol/price/timeを記録する。
- **Expected failure modes**: endpoint遮断、timestamp欠損、契約種別不一致、quote差。
- **Recovery / rollback**: sourceを推測で補わず、BLOCKEDまたはsource再選定へ戻す。
- **Evidence**: —

### CP-02: Pure contract and public adapters

- **Status**: completed
- **Goal**: network responseをstrict modelへ変換し、3/3 freshnessとmedian/spreadを決定的に計算する。
- **Linked ACs**: AC-02、AC-04
- **Dependencies**: CP-01。
- **Targets**: Python domain、adapter、focused tests。
- **Work**: REDからsource parser、canonical symbol mapping、collector payloadを実装する。
- **Preserve / Do not change**: lockfile、Bitget既存client、取引機能を変更しない。
- **Completion criteria**: invalid、missing、stale、timestamp差のtestが通る。
- **Verification**: `uv run pytest -q tests/test_market_comparison.py`。
- **Expected failure modes**: upstream field drift、非数値、HTTP timeout。
- **Recovery / rollback**: adapter単位で除去可能。既存laneへfallbackしない。
- **Evidence**: —

### CP-03: Service optional sidecar

- **Status**: completed
- **Goal**: 独立5分taskをservice lifecycleへ接続し、Cold snapshotへoptional blockを載せる。
- **Linked ACs**: AC-03、AC-05、AC-07
- **Dependencies**: CP-02。
- **Targets**: application collector、service snapshot、CLI、runtime tests。
- **Work**: in-memory latest block、fail-open refresh、cancel/await、snapshot injectionを追加する。
- **Preserve / Do not change**: DB、schema required field、ranking/rows、Hot tickerを変更しない。
- **Completion criteria**: source障害でもsnapshot発行、shutdown、既存結果が不変。
- **Verification**: focused snapshot/runtime tests。
- **Expected failure modes**: network task leak、shutdown遅延、古いblockの誤表示。
- **Recovery / rollback**: taskとoptional injectionを外すだけでmain相当へ戻せる。
- **Evidence**: —

### CP-04: Fail-closed Dashboard display

- **Status**: completed
- **Goal**: 選択中のpilot銘柄へ比較情報を読みやすく表示する。
- **Linked ACs**: AC-04、AC-06
- **Dependencies**: CP-03。
- **Targets**: TypeScript parser、Svelte detail component、Dashboard route、tests。
- **Work**: local parser、Japanese labels、coverage/stale/error、raw/median/spread表示を追加する。
- **Preserve / Do not change**: focus order、VPI、Watchlist、chart、color/font契約。
- **Completion criteria**: 3/3、2/3、stale、対象外が期待どおり表示または非表示になる。
- **Verification**: Vitest、Playwright desktop/390px、Svelte check。
- **Expected failure modes**: information overload、overflow、invalid payload表示。
- **Recovery / rollback**: parser/component/route接続を除去し、sidecarは無視できる。
- **Evidence**: —

### CP-05: Runnable gate and optional qualification

- **Status**: completed
- **Goal**: まず動作可能な縦切りを確認し、長期観測は価値判断が必要な場合だけ後続化する。
- **Linked ACs**: AC-08、AC-09
- **Dependencies**: CP-04。
- **Targets**: isolated state、docs、final diff。
- **Work**: focused gate、live API smoke、画面smoke、final diffを確認する。24時間観測はdeferred。
- **Preserve / Do not change**: 現役DuckDBへ別writerを接続しない。全銘柄化しない。
- **Completion criteria**: mandatory ACの証拠が揃い、サービスから画面までの縦切りが再現できる。
- **Verification**: focused pytest、Ruff、Vitest、Svelte check/build、live collector、browser smoke、docs/diff check。
- **Expected failure modes**: source欠損、rate limit、継続的stale、表示価値なし。
- **Recovery / rollback**: pilotを削除または既定無効化し、Bitget-onlyを維持する。
- **Evidence**: —

## 4. Critical risks and stop conditions

| ID | Risk / Stop condition | Detection | Mitigation / Resume requirement | Status |
|---|---|---|---|---|
| R-01 | 三社値が同じ指標として比較不能 | CP-01 contract tableに必須field不一致 | medianを実装せずsource再選定または計画終了 | open |
| R-02 | private API、秘密情報、注文系dependencyが必要 | endpoint/client要求 | 即停止。public-only代替の承認が必要 | open |
| R-03 | service障害やshutdown遅延へ波及 | focused runtime test、isolated stop | taskを切離し、snapshotはsidecarなしで継続 | open |
| R-04 | DB/schema migrationまたは別writerが必要 | final design/diff | scope超過として停止し再計画 | open |
| R-05 | 2/3以下やstaleからmedianを生成してしまう | pure/parser tests | fail-closedをmandatoryに維持 | open |
| R-06 | 画面情報量が判断を悪化させる | responsive/E2E/利用観察 | panel縮小またはpilot終了 | open |
| R-07 | 24時間観測で比較価値が見えない | spreadと利用結果 | 全銘柄化せず計画終了 | open |

## 5. Progress, decisions, findings, evidence

- 2026-08-11 19:48 — ユーザーが限定案を承認。`main@953589b`はclean。
- 2026-08-11 19:48 — `ai/multisource-display-pilot-20260811-1948`を作成。
- 2026-08-11 19:48 — 新規dependencyなし、既存pybotters、3銘柄、5分REST、表示専用、ranking非接続を確定。

## 6. Final result

- **Result**: runnable
- **Actual state**: 3社public REST、3/3中央値、optional snapshot sidecar、Selected detailを実装。live collectorは3銘柄すべて3/3、実ブラウザE2Eも成功した。
- **Goal gap**: runnable化のmandatory implementation gapはなし。Git publicationとruntime反映はdelivery手順として別に実施する。
- **Verification summary**: Python関連50 passed、Ruff/Pyrefly、Web全227 passed、Svelte check/build、追加E2E 1 passed、live API smoke、docs checker、`git diff --check`成功。
- **Residual risks**: USD/USDT差と長時間のAPI安定性は未評価。値は表示専用でrankingや売買判定へ使わない。
- **Remaining work / Resume requirement**: implementation作業なし。必要なら別作業として24時間観測を行う。
