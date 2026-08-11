# ExecPlan: 3市場mark price表示pilotとPerp venue限定拡張

- 作成: `2026-08-11T19:48:00+09:00`
- 更新: `2026-08-12T00:57:18+09:00`
- 状態: `実装計画`
- Plan ID: `2026-08-11-multisource-display-pilot`
- Profile / risk: `EXECPLAN / MEDIUM`
- Base revision: `953589b744cc083fb41c7e2845fb5ac4517b68cd`
- Current checkpoint: `CP-11 in progress`

## 0. 結論と現在地

- **Target**: 完了済みBTC/ETH/SOL pilotのHyperliquid quoteを正し、契約同等性を確認できたBitget USDT Perpとdefault Hyperliquid Core Perpについて、会場別mark、funding、OI、24h notional volumeをoptional sidecarで選択銘柄へ表示する。rankingや売買判定には接続しない。
- **現在地**: 初回runtimeでは161件readyだったが、次の一時的な片側取得障害で契約mappingごと失われ、`items=[]`が継続公開された。P0回復性修正を再開した。
- **次の行動**: 成功→片側障害→回復のREDテストから、契約catalogの有期限保持、source状態公開、周期task継続を実装し、3回連続live cycleまで確認する。
- **最大のRisk / Blocker**: 同名symbolでもquote、collateral、倍率、OI単位、funding interval、oracleが一致するとは限らない。必須単位を確認できない契約はmappingせず、比較値を生成しない。

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
- optional Cold snapshot sidecarとして公開し、scanner rowsから独立したDashboard panelへ表示する。

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
| AC-06 | yes | Dashboardにraw値、source、quote、時刻、coverage、spread、medianまたは明示的欠損理由を表示する | user | parser unit、build、browser smoke | verified | 対象scanner rowなしのparser/check/buildとsystem Chrome E2E成功 |
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
- **Goal**: scanner rowsに依存せず、固定3銘柄の比較情報を読みやすく表示する。
- **Linked ACs**: AC-04、AC-06
- **Dependencies**: CP-03。
- **Targets**: TypeScript parser、Svelte Dashboard panel、Dashboard route、tests。
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

## 3.1 承認済み後続限定拡張

### Objective

- BitgetまたはHyperliquidを全体の主系に固定せず、会場別Perp契約を独立した観測単位として扱う。
- 現行Bitget scannerのCandidateを変えず、同等性を確認できたdefault Hyperliquid Core契約の会場情報を選択銘柄へ追加する。
- 全銘柄化、会場横断ranking、Hyperliquid専用履歴laneへ進む前に、mapping、単位、取得継続性、表示価値を検証する。

### Target

- 旧pilotのBTC/ETH/SOLについてHyperliquid quoteを`USDT`へ訂正し、`USD / USDT` caveatを修正する。
- 新しいoptional `summary.perpVenueComparison` sidecarを追加し、BitgetとHyperliquid Coreの会場別raw値と比較可否を保持する。
- 対象はBitget USDT perpetualとdefault Hyperliquid Coreの暗号資産Perpだけとし、契約同等性を説明できるものだけmappingする。
- Webは全mapping一覧ではなく、現在選択中のscanner rowに一致する会場情報だけをSelected detailへ表示する。
- 取得周期は現行pilotと同じ300秒とし、source単位の失敗を既存scannerから隔離する。

### Preserve

- 旧`summary.marketComparison` v1と3/3 fail-closed契約。quote/copy修正以外は意味を変更しない。
- Bitgetを使う既存Candidate、Watchlist、Raw Sort、Smart Rank、VPI、74h/OI、category、Hot ticker、chart。
- snapshot required schema、DB schema、state layout、single writer、service shutdown。
- public data only、注文・残高・position・wallet・API keyなしの製品境界。

### Non-goals / Deferred

- Hyperliquid専用銘柄のcandles、履歴、data quality、Candidate、ranking。
- HIP-3、RWA、株式、商品、指数、現物、期日物。
- Bybit比較の全銘柄化、TradingView取得、3市場medianのranking接続。
- 板を同一notionalで歩かせるslippage比較、裁定機会判定、通知、注文。
- DB永続化、migration、別writer、新規production dependency。
- `Bitget / Hyperliquid / 両会場`でscanner universeを切り替えるfilter。Hyperliquid専用laneがない段階では意味が不完全なため後続判断とする。

### Acceptance criteria

| ID | Mandatory | Condition | Source | Verification | Status | Evidence |
|---|---:|---|---|---|---|---|
| AC-10 | yes | BTC/ETH/SOLのHyperliquid quoteとUI/docsが`USDT`へ訂正され、旧3/3 fail-closed契約を維持する | user / primary spec | Python、Vitest、E2E、docs diff | verified | quote unit/Vitest/E2E成功 |
| AC-11 | yes | mapped契約ごとにunderlying、quote、collateral、倍率またはOI単位、funding interval、listing statusを説明でき、曖昧な契約を自動統合しない | user / unresolved | primary-spec probe、pure mapping tests | verified | 公式仕様、live 745/232 probe、fail-closed mapping test |
| AC-12 | yes | optional `summary.perpVenueComparison`がBitget/Hyperliquidのsource symbol、単位、mark、比較可能なfunding/OI/volume、observedAt、nullable sourceAt、欠損理由を保持する | user | serializer/parser tests、live smoke | verified | live 161 mapping、serializer/parser test |
| AC-13 | yes | Webは選択中scanner symbolの会場情報だけを表示し、unmapped、stale、片側欠損を誤って比較しない | user / repo | Vitest、1440px/390px E2E | verified | 関連E2E 2 passed |
| AC-14 | yes | 新collectorの失敗が既存scanner、snapshot発行、shutdownへ波及せず、DB、required schema、ranking、Candidateを変更しない | repo / default | service/snapshot tests、final diff | verified | focused service/snapshot 48 passed、schema/DB差分なし |
| AC-15 | yes | focused test、Ruff、Pyrefly、Web check/build、関連E2E、live public API smoke、docs/diff checkが成功する | repo | recorded commands and exit codes | verified | `verify-local.sh`成功、Python 255、Web 230、E2E 70 passed。再起動後sidecar 161件、実画面Desktop/Mobile確認 |
| AC-16 | no | 最低72時間・864予定cycleでsource別成功、欠損、stale、応答時間、field充足、mapping、snapshot遅延を隔離観測する | follow-up | qualification artifact | deferred | 実装完了とは分離 |
| AC-17 | yes | 初回成功後の片側取得障害でmappingを消さず、観測値を再利用せず該当会場を`unavailable`にし、回復周期でfresh値へ戻る。契約catalogは最大30分で失効し、source status/error/observedAtを公開する | user / runtime regression | sequence unit test、3回連続live cycle、snapshot inspection | pending | 2026-08-12 runtimeで161件から0件への退行を確認 |

### CP-06: Contract and unit probe

- **Status**: completed
- **Goal**: BitgetとHyperliquid Coreの対応可否と比較可能なfieldを一次仕様・実応答で確定する。
- **Linked ACs**: AC-10、AC-11、AC-12
- **Dependencies**: public endpointsへのnetwork access。
- **Targets**: official docs、read-only probe output、plan。production code変更なし。
- **Work**: underlying、quote、collateral、倍率またはOI単位、funding interval、listing status、source timestamp、24h volume定義を照合する。
- **Preserve / Do not change**: symbol名だけでmappingしない。確認不能fieldを推測しない。
- **Completion criteria**: mandatory payload fieldと除外条件に未解決の意味差がない。解消できなければ対象または指標を縮小する。
- **Verification**: Bitget contract/tickerとHyperliquid meta/contextのfixture化可能なresponse shapeを記録する。
- **Expected failure modes**: multiplier不明、volume窓不一致、quote例外、source timestamp欠損。
- **Recovery / rollback**: 比較不能fieldまたは契約を対象外にし、mark-onlyまたは旧pilotへ戻す。
- **Evidence**: —

### CP-07: Pure mapping and public adapters

- **Status**: completed
- **Goal**: 会場別契約を観測単位、canonical assetを表示groupとするfail-closed mappingとpublic fetchを実装する。
- **Linked ACs**: AC-11、AC-12
- **Dependencies**: CP-06。
- **Targets**: `domain/perp_venue_comparison.py`、`adapters/perp_venue_public.py`、focused Python tests。
- **Work**: mapped/unmapped、stale、片側欠損、quote/multiplier例外をpure testsから実装し、Bitget/Hyperliquidをsource別に取得する。
- **Preserve / Do not change**: Bybit、HIP-3、private API、WebSocket、新規dependencyを接続しない。raw OIを合算しない。
- **Completion criteria**: 比較可能なfieldだけを公開し、曖昧な契約はunmappedまたはfield nullになる。
- **Verification**: `uv run pytest -q tests/test_perp_venue_comparison.py tests/test_market_comparison.py`、Ruff、Pyrefly。
- **Expected failure modes**: upstream field drift、重複canonical key、全source失敗、過大payload。
- **Recovery / rollback**: 新domain/adapterを削除すれば旧pilotへ戻せる。
- **Evidence**: —

### CP-08: Optional service sidecar

- **Status**: completed
- **Goal**: 300秒の独立in-memory collectorをservice lifecycleへ追加し、Cold snapshotへoptional blockを載せる。
- **Linked ACs**: AC-12、AC-14
- **Dependencies**: CP-07。
- **Targets**: `application/perp_venue_comparison.py`、`service_snapshot.py`、`cli.py`、service/snapshot tests。
- **Work**: 起動、manual publish、periodic refresh、cancel/await、optional injectionを追加する。
- **Preserve / Do not change**: DB、required schema、single writer、既存marketComparison、ranking、Candidateを変更しない。
- **Completion criteria**: 新collector全失敗でも旧snapshotが発行され、shutdown時にtask leakがない。
- **Verification**: focused service/snapshot testsとisolated stop。
- **Expected failure modes**: timeout、task leak、snapshot肥大、旧blockの長期残存。
- **Recovery / rollback**: taskとoptional injectionを外して旧pilotへ戻す。
- **Evidence**: —

### CP-09: Selected-symbol display

- **Status**: completed
- **Goal**: 選択中scanner symbolだけに会場別raw値、単位、鮮度、比較不能理由を表示する。
- **Linked ACs**: AC-10、AC-13
- **Dependencies**: CP-08。
- **Targets**: Web parser、`SelectedSymbolVenueComparison.svelte`、Dashboard route、Vitest、E2E、current docs。
- **Work**: parserをfail-closedにし、Selected detailへ局所接続する。固定全銘柄cardやuniverse filterは追加しない。
- **Preserve / Do not change**: Candidate→Watchlist→Selected detail→Smart RankのDOM/keyboard順、bounded scroll、color/font契約。
- **Completion criteria**: mapped、片側欠損、stale、unmappedについて期待どおり表示または非表示になる。
- **Verification**: Vitest、Svelte check/build、1440px/390px関連E2E。
- **Expected failure modes**: detail過密、単位誤認、モバイルoverflow、invalid payload表示。
- **Recovery / rollback**: 新component/route接続を外し、sidecarはWebから無視できる。
- **Evidence**: —

### CP-10: Final gate and optional qualification

- **Status**: completed
- **Goal**: 実装のmandatory ACを検証し、72時間観測は別のqualificationとして扱う。
- **Linked ACs**: AC-15、AC-16
- **Dependencies**: CP-09。
- **Targets**: focused/full gate、live smoke、docs、final diff、任意の隔離qualification artifact。
- **Work**: test/check/build/E2E/live smoke/final diffを確認し、必要な場合だけ72時間観測を開始する。
- **Preserve / Do not change**: 現役DuckDBへ別writerを接続しない。観測未実施を成功扱いしない。
- **Completion criteria**: mandatory ACに再現可能な証拠があり、final diffがAllowedFilesとTargetに一致する。
- **Verification**: `.codex/SP_STATE.md`のTestCommand、関連E2E、live public API smoke、docs checker、`git diff --check`。
- **Expected failure modes**: intermittent API欠損、既存snapshot遅延、payload肥大、利用価値なし。
- **Recovery / rollback**: 新sidecarを無効化または除去し、旧pilot/Bitget scannerを維持する。
- **Evidence**: `bash scripts/verify-local.sh`成功。再起動後の`perp_venue_comparison_v1`は161件すべてready。`0GUSDT`を1440pxと390pxで開き、2会場の価格、Funding、建玉想定元本、24h出来高、USDT/USDC表示と横overflowなしを確認。

### CP-11: P0 comparison recovery

- **Status**: in progress
- **Goal**: 一時的な片側取得障害を契約mapping消失へ波及させず、fresh観測だけでpartial/unavailableと回復を公開する。
- **Linked ACs**: AC-17
- **Dependencies**: CP-10、2026-08-12 runtime再現。
- **Targets**: Perp比較application/domain、focused tests、CLI logging、contract docs、active plan。
- **Work**: 検証済み契約catalogだけを最大30分保持し、会場別status/error/observedAtをsidecarへ追加する。観測値は毎周期置換し、内部例外後もperiodic loopを継続する。
- **Preserve / Do not change**: market値を再利用しない。DB、required schema、Candidate、ranking、Web表示順、新規dependencyを変更しない。
- **Completion criteria**: success→片側障害→recovery testが通り、実serviceで3回連続のsidecar生成と非空mappingを確認する。
- **Verification**: focused pytest、Ruff、Pyrefly、Web parser/check/build、full local gate、live snapshot 3 cycle、single writer、unit health。
- **Expected failure modes**: catalog期限切れ、両source障害、periodic task終了、error非公開、回復値未反映。
- **Recovery / rollback**: P0 commitをrevertして旧実装へ戻せるが、0件化を既知riskとして残すためmergeしない。
- **Evidence**: 2026-08-12 00:12 snapshotは`perpGeneratedAt=1786461001061`、`items=0`。同時刻帯の隔離probeはBitget 745、Hyperliquid 232を取得でき、恒久的なAPI停止ではなかった。success→failure→recovery、30分失効、periodic内部例外継続のfocused test 4件とfull local gateが成功した。初回再起動後のcycle 2は両source `TimeoutError`だったが、161件を消さず全件unavailableで維持した。30秒offset後もtimeoutしたため位相競合仮説を棄却し、periodic fetchをworker thread内の独立event loopへ隔離した。

## 4. Critical risks and stop conditions

| ID | Risk / Stop condition | Detection | Mitigation / Resume requirement | Status |
|---|---|---|---|---|
| R-01 | 三社値が同じ指標として比較不能 | CP-01 contract tableに必須field不一致 | medianを実装せずsource再選定または計画終了 | open |
| R-02 | private API、秘密情報、注文系dependencyが必要 | endpoint/client要求 | 即停止。public-only代替の承認が必要 | open |
| R-03 | service障害やshutdown遅延へ波及 | focused runtime test、isolated stop | taskを切離し、snapshotはsidecarなしで継続 | open |
| R-04 | DB/schema migrationまたは別writerが必要 | final design/diff | scope超過として停止し再計画 | open |
| R-05 | 2/3以下やstaleからmedianを生成してしまう | pure/parser tests | fail-closedをmandatoryに維持 | open |
| R-06 | 画面情報量が判断を悪化させる | responsive/E2E/利用観察 | panel縮小またはpilot終了 | open |
| R-07 | 72時間限定観測で比較価値が見えない | source継続性と表示利用結果 | 全銘柄化せず限定拡張を維持または終了 | open |
| R-08 | symbol名一致だけでは契約同等性を確定できない | CP-06 probe、mapping test | unmappedにして対象外。明示規則の根拠が必要 | open |
| R-09 | quote、collateral、倍率、OI単位、funding intervalを確定できない | primary spec/responseに根拠なし | 対象fieldまたは契約を除外。推測で補わない | open |
| R-10 | source timestamp欠損から鮮度を偽装する | Hyperliquid responseにtimeなし | `sourceAt: null`を維持し、observedAtと区別 | open |
| R-11 | 新sidecarがsnapshot肥大またはservice遅延を起こす | focused runtime/performance、publish duration | payloadをmapping済みに限定するかsidecarを撤回 | open |
| R-12 | Selected detailが過密化し監視判断を悪化させる | 1440px/390px E2Eと利用観察 | componentを縮小または非表示化 | open |
| R-13 | Hyperliquid専用lane、DB migration、別writerが必要になる | CP-06〜09でscope越境を検出 | 今回停止し、別EXECPLANと明示承認が必要 | open |

## 5. Progress, decisions, findings, evidence

- 2026-08-11 19:48 — ユーザーが限定案を承認。`main@953589b`はclean。
- 2026-08-11 19:48 — `ai/multisource-display-pilot-20260811-1948`を作成。
- 2026-08-11 19:48 — 新規dependencyなし、既存pybotters、3銘柄、5分REST、表示専用、ranking非接続を確定。
- 2026-08-11 21:39 — 初回runtime確認で比較sidecarは3銘柄3/3だったが、live scanner rowsにBTC/ETH/SOLがなくSelected detailへ到達不能と判明。
- 2026-08-11 21:46 — scanner rowsから独立したDashboard panelへ修正し、同条件のE2EをREDからGREENへした。
- 2026-08-11 22:56 — ユーザーが会場を全体の主系に固定せず、旧pilot訂正と検証済み重複銘柄へのHyperliquid Core sidecarだけを次に実装する限定方針を承認。CP-06〜10とAC-10〜16を追加した。
- 2026-08-11 — 一次仕様とlive responseを照合し、Bitget 745、Hyperliquid Core 232から完全一致・除外規則で161件をmapping。quote訂正、collector、optional sidecar、Selected detail、関連unit/E2Eを実装した。
- 2026-08-11 23:38 — `bash scripts/verify-local.sh`が成功。Python 255、Web unit 230、Playwright E2E 70 passed、Ruff、Pyrefly、Svelte check/build、文書検証を完了した。
- 2026-08-11 23:40 — 実装を`66cb8be`としてcommitし、`origin/ai/multisource-display-pilot-20260811-1948`へpushした。
- 2026-08-11 23:41 — `prep-watchdeck-service.service`と`prep-watchdeck-web.service`を各1回再起動。MainPIDはservice `194784`→`696007`、Web `228335`→`696008`、両unitとも`active/running`、`NRestarts=0`。DuckDB writerは1 processを維持した。
- 2026-08-11 23:46 — fresh snapshotの`perp_venue_comparison_v1` 161件すべてreadyを確認し、実サービスの`0GUSDT`でDesktopと390×844の会場比較表示、USDT/USDC単位、横overflowなしを確認した。
- 2026-08-12 00:12 — 後続snapshotで`perpVenueComparison.items=[]`への退行を確認。service/Webは`active/running`だったため、初回成功だけでは継続利用を証明できないと判断し、AC-17 / CP-11を追加した。
- 2026-08-12 00:33 — 契約catalogだけの30分TTL、各周期のfresh観測、会場別source状態、periodic内部例外のfail-closed継続、service logを実装。Python 258、Web 230、E2E 70を含む`verify-local.sh`とisolated live 161件取得が成功した。
- 2026-08-12 00:43 — cycle 2で両sourceが20秒timeoutしたが、修正後はmapping 161件を全件unavailableとして維持した。snapshot生成・旧3市場refreshと同一位相の負荷競合を避けるため、Perp periodicの初回だけ30秒offsetを追加した。
- 2026-08-12 00:54 — 30秒offset後もcycle 2が両source timeoutしたため仮説を棄却。Context7でpybotters Client利用形を再確認し、periodic HTTP fetchをworker thread内の独立event loopへ隔離するRED→GREENを追加した。

## 6. Final result

- **Result**: PARTIAL（AC-10〜15は実装済み、runtime退行によりmandatory AC-17を追加して修正中）
- **Actual state**: 初回は161件readyだったが、後続周期で比較itemsが0件になり、現在の実装は片側障害時の継続表示契約を満たさない。
- **Goal gap**: AC-17 / CP-11。72時間qualification以前に、3回連続live cycleと障害回復を確認する必要がある。
- **Verification summary**: Python 255 passed、Ruff/Pyrefly成功、Web unit 230 passed、Svelte check/build成功、Playwright E2E 70 passed、docs checker、`git diff --check`、live public API smoke成功。再起動後は両unit `active/running`、`NRestarts=0`、single DuckDB writer、sidecar 161件すべてready、実画面Desktop/Mobile表示を確認した。
- **Residual risks**: 72時間連続のAPI継続性は未確認。既存scanner側には今回の変更外であるsnapshot遅延・データ品質低下が残る。比較値はUSDTとUSDCを換算せず、ranking、Candidate、売買・裁定判断へ接続していない。
- **Remaining work / Resume requirement**: CP-11の最小RED→GREEN、full gate、commit/push、再起動、3回連続live cycle。完了後だけPASSへ戻す。
