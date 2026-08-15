# 3 Venue Crypto Perp Universe Replacement

- 作成: `2026-08-14T19:43:00+09:00`
- 更新: `2026-08-15T03:21:05+09:00`
- 状態: `実装計画`
- branch: `ai/perp-universe-replacement-20260814-1943`
- base: `origin/main@c4c68a9`
- mode / risk: `EXECPLAN / HIGH`

## Objective

Bitget、Hyperliquid Core、Asterのcrypto linear perpetualを、単位・鮮度・由来を失わずに監視し、
中立なUniverse Explorerで比較できるlocal-firstアプリを、現行runtimeを変更せずshadowし、
別承認後に置換できる状態まで実装する。

## Target

- 3 Venueのcatalog、60秒L1、全対象1分足、選択groupのdepth/tradeを取得する。
- Postgres 17を運用正本、確定済みParquetを期限後の履歴正本、JSONを再生成可能read modelとする。
- markのみ、厳格なfreshnessとidentity条件下でparity参考中央値を表示する。
- Chart、theme/font、Past Note機能を維持し、旧rank/Candidate/VPI/3市場pilotを置換UIから除去する。
- 現行runtimeを変更せずshadowし、証拠が揃った後だけcutover承認点へ到達する。

## Preserve

- 自動売買、注文、残高、position、秘密API keyを追加しない。
- 稼働中の`/home/tn/projects/prep-watchdeck`、現役DuckDB、既存systemd unit、未追跡文書を
  cutoverの明示承認と実行まで変更しない。
- `/home/tn/projects/justpass`のPostgres、port 5432、container、volumeへ接触しない。
- `DESIGN.md`のsemantic color、font、shape、accessibilityを維持する。
- 欠損、stale、単位不明をfail-closedで公開し、古い値をfreshとして再利用しない。

## Non-goals

- 4 Venue目、CCXT/CCXT Pro/implicit runtime、Discovery job、RWA、HIP-3、synthetic、RFQ、multiplier contract。
- 全市場order-book raw、深いhistorical backfill、売買推奨、裁定通知、価格差ranking。
- push、merge、live cutover、旧state削除。これらは別の明示承認を要する。

## Decisions

### Runtime boundary

- 新packageは`apps/market-core`、CLIは`watchdeck-market`。旧`scanner-core`をimportしない。
- 新state rootは`~/.local/share/prep-watchdeck-market`。
- WebはPostgresへ接続せず、schema検証済みatomic JSONだけを読む。
- 新依存は既存Python stackに`psycopg[binary,pool]`を追加する。ParquetはPolars、WSはaiohttpを使う。
- CCXTは3 VenueでVenue固有contract/finality/shardingを除去できないため初期runtimeへ追加しない。

### Source contracts

- Bitget: active `USDT-FUTURES` perpetual、`quoteCoin=USDT`、`isRwa=false`。L1はall ticker。
  確定1分足はfinished candle APIを120秒ごとに分散取得し、直近3本をdedupeする。
- Hyperliquid: default Core、non-delisted、非HIP-3。L1は`metaAndAssetCtxs`、BBOは`l2Book` WS。
  1分足は足終了5秒後の最終受信値を`derived_final`として保存し、source-confirmedとは表示しない。
  gapは補間しない。`oraclePx`は`referencePriceKind=oracle`、timestamp不在時は`sourceAt=null`。
- Aster: V3 `PERPETUAL`、`TRADING`、`underlyingType=COIN`、USDT linear。
  L1はall-market mark/bookTicker/24h ticker。1分足はkline `x=true`のみ。OIは公式契約不足のためnull。
- Catalogは15分、L1はfixed-rate 60秒、single-flight。Venue timeout 20秒、cycle deadline 50秒。

### Identity and metrics

- `venueInstrumentId=<venue>:<sourceSymbol>`。
- 自動groupはactive crypto linear perp、base完全一致、base数量契約、multiplier=1確認済み、
  同一Venue候補1件だけ。`groupId=crypto:<BASE>:linear-perp`、`mappingMethod=exact_base_heuristic`。
- alias、衝突、単位不明はVenue単独instrumentのままにする。
- `markPrice`と`referencePrice`を分離し、`referencePriceKind=index|oracle|none`を持つ。
- Fundingはraw/interval/next funding、interval確認時だけ1時間換算。OIはraw/unitを保持し、確認時だけbase/notional。
- 24h volumeはVenue別。medianは作らない。
- mark参考中央値は同一groupの2 Venue以上、同一cycle、age 120秒以内、skew 30秒以内だけ。
  USDT/USDC/USD parity仮定を明示し、価格差rank、通知、裁定表現へ接続しない。

### Storage truth

- Postgres: catalog raw changes、instrument version、capability、identity、latest L1、collector run、
  直近7日raw、直近8日normalized、archive checkpoint。
- Parquet: `dataset=<type>/venue=<venue>/date=YYYY-MM-DD/`。market state 1m、candle 1m、存在する
  `funding_events`。現行collectorに`funding_events`のproducerはなく、funding値は
  `market_state_1m`に保持する。同tableが空であることは収集失敗と扱わない。
  ZSTD、毎時maintenanceで各dataset/Venueの最古未archive日から重複を除いた最大3日と指定日を処理し、
  最終4 file以下。manifestにschema version、generation、row count、unique key、
  min/max timestamp、SHA-256を持つ。Postgresとの100%照合とreadback後だけ確定する。
- Rawは7日+最大2時間を保持する。現行schemaはDEFAULT partitionだけなので、1回最大10,000行の
  bounded DELETEで段階削除する。大型GIN indexは作らない。
- Late correctionは新generationを作り、manifestをatomicに切り替える。
- JSON artifactは`universe-snapshot`、`market-chart`、`selected-market`、`service-state`。

### UI and selection

- 主画面はinstrument行のUniverse Explorer。既定sortはbase、次にVenue。
- 検索、Venue、coverage、status/quality filter、Venue別L1、group比較、参考mark中央値を表示する。
- 選択はlocal single-userで1 group、last-write-wins、500ms debounce、15分TTL、5分heartbeat。
  旧subscriptionは10秒以内に解除する。
- 選択groupの最大20段、直近100 trades、$100/$500/$1,000板上概算を表示する。
  10秒超、板不足、非USD-likeではnull。fee/将来impact/注文可否を含まないと明記する。
- Chartは選択instrumentだけ生成し、5m/15m/1h/4h/24hを維持する。
- Past Noteは新stateで`venueInstrumentId`へ保存する。旧Bitget noteをheuristic groupへ自動移行しない。

## Acceptance Criteria

- AC-01: 3 Venue catalogが3回連続成功し、除外・provenance・capabilityが保存される。
- AC-02: identity collision/multiplier/unknownが自動group化されない。
- AC-03: 60秒cycle p95<=30秒、max<=50秒、overlap/backlog 0、429 0。
- AC-04: L1 fresh<=120秒が99%以上。95%未満が2周期続けば失敗。
- AC-05: 受信したconfirmed/derived candleの保存率100%、duplicate 0、activeの95%以上に直近5分bar。
- AC-06: Aster OIは明示null、Hyperliquid oracleをindexとして公開しない。
- AC-07: Postgres commit p95<=2秒、connection leak/次cycleまで続くlock 0。
- AC-08: ParquetとPostgresのrow count/key/timestamp/checksumが100%一致する。
- AC-09: selected変更後10秒以内に旧購読解除、orphan 0、板上概算がfail-closedである。
- AC-10: Web主要flowが1440px/390pxで動き、欠損と由来を隠さず、売買推奨表現がない。
- AC-11: 60分shadowで現行snapshot p95がbaseline比120%以内、NRestarts=0、DuckDB writer 1。
- AC-12: `7*raw_GB/day + 365*parquet_GB/day + 30GB <= 0.75*shadow開始時free`。
- AC-13: cutover前に旧worktree/unit/stateが即時復元可能である。

## Checkpoints

### CP-00 Contract and isolated worktree — COMPLETE

専用worktree、branch、EXECPLAN、SP_STATEを作成し、旧runtimeを変更していないことを確認する。

Evidence: `git diff --check`成功。live worktreeは既存untracked assessmentのみでscanner/Webはactive。

### CP-01 Postgres and package — COMPLETE

新workspace、CLI、Compose、SQL migration、health、backup/restoreを実装する。外部Venueには接続しない。

Evidence: dedicated Postgres 17 containerをport 55433で一時起動し、CLI migrationは初回`applied=1`、
2回目`applied=0`、health ready。実DBを含む6 tests、Ruff、Pyreflyに成功しcontainerを削除した。
Composeはport 55432・repo外state/env・固定digestで検証済み。backup/restore入口は引数と対象を
fail-closedで検証し、実restoreは未実行。

### CP-02 Catalog and identity — COMPLETE

3 adapterのfixture契約、raw hash dedupe、SCD2、capability、exact-base heuristicを実装する。

Evidence: 3 Venue parser tableとidentity tableが成功。volatile source timestampをsemantic catalog hashから
分離した。disposable Postgresでraw dedupe、2 migrations、SCD2、capability、exclusion、identity履歴、
membershipを確認。collision/multiplier/unknown quantityはunmapped。Bitget/Hyperliquid catalogを
read-onlyで各1回確認し、Aster live確認は公式V3 hostへ訂正後CP-08へ残した。

### CP-03 L1 and candles — COMPLETE

fixed-rate L1、partial failure、Bitget confirmed、Hyperliquid derived、Aster confirmed candleを実装する。

Evidence: 3 Venue L1を20秒fetch上限・50秒cycle budget・single-flightで接続し、missing instrumentを
unavailableで上書きする。Bitget confirmed candle、Hyperliquid end+5秒derived final、Aster x=true
confirmed candleをbounded queueと1接続writerへ接続した。CatalogはDB persist成功Venueだけを
in-memory publishし、catalog transitionとcandle flushを同一lockで直列化、removed instrumentの
queued candleをflush時に除外する。Candleは1分全体が単一instrument versionの有効期間内にある場合だけ
保存し、catalog境界を跨ぐbarをfail-closedで拒否する。focused 25 tests passed、実Postgres integration 7 passed、
Ruff/format/Pyrefly成功。外部API・live runtimeは未操作。

### CP-04 Archive — COMPLETE

Parquet manifest、readback、generation、raw retentionを実装する。

Evidence: market state/candle/fundingをZSTD Parquetへgeneration付きで書き、row count、unique key、
timestamp、row digest、file SHA-256のreadback一致後だけmanifestをatomic confirmする。現行+最新3件の
superseded fileだけを残す。normalized 8日はconfirmed manifestとfile SHAを再確認後だけ削除する。
`raw_market_observations`はParquet対象外のephemeral rawとして7日+2時間後に削除する。各DELETEは
最大10,000行で、現行raw tableがDEFAULT partitionのみのため、承認案のpartition dropではなく
bounded DELETEを採用した。毎時maintenanceは最古未archive日から最大3日と指定日を処理する。
実Postgres integration 1 passed、Ruff/format/Pyrefly、uv lock check成功。

### CP-05 Selected data — COMPLETE

単一group control、depth/trade、TTL、subscription cleanup、板上概算を実装する。

Evidence: component testで単一group、primary switch、TTL、stream開始失敗後のcleanupを確認した。
最終shadowで旧leaseのraw 17,380行がsupersede後0、cleanup 0秒、orphan 0、同一commandから
新UUID leaseへ再有効化することを確認した。

### CP-06 Universe Explorer — COMPLETE

schema/type generation、SvelteKit reader/API/UI、Chart、Past Noteを実装する。

Evidence: Web unit 54 passed、Svelte check 0 errors/0 warnings、build成功、Playwright 1440px/390px
2 casesに成功した。最終shadowの実画面でUniverse、selected detail、参考median、Chart、
3 Venue depth/trades、Past Noteに到達でき、横overflow、売買推奨、裁定断定がないことを
確認した。Past NoteのAPI save/readbackも一致した。

### CP-07 Replacement cleanup and verification — COMPLETE

新worktree内だけで旧runtime/UIを除去し、env/ignore、起動・更新・systemd installer、current docsを
新service境界へ揃え、focused gatesと`verify-local.sh`を1回実行する。

Evidence: 完了まで走った`verify-local.sh`は1回でexit 0。先行した1回はcaller timeoutで中断し、
合否証拠にせずcleanupした。成功full gate後のAster host/candle temporal admission、TTL再有効化、
real-DB rowcount、shadow cleanup/gateの限定修正は関連focused testとCP-08 shadowで確認した。
したがって、成功済みfull gateを最終tree全体の実行結果とは扱わない。

### CP-08 Isolated live smoke and shadow — COMPLETE

専用DB/state/portで3 Venue smoke、15分baseline、60分shadow、容量投影を1回だけ実施する。

Accepted evidence:
`/home/tn/.local/share/prep-watchdeck-market-evidence-20260815-0153/20260814T165229Z-035b51e2`。
harnessはexit 0、cleanup 0、`summary.json.status=pass`、source digest before/after一致。
`summary.json`だけでCP-08合格とせず、手動照合を含めて次を確認した。

| AC | 証拠と結果 |
| --- | --- |
| AC-01 | 直近3 catalog runがすべてsuccess、各1177/1177。provenance、capability、exclusionもVenueごとに保存。 |
| AC-02 | collision/multiplier/quantity unknownをunmappedにするfixtureと実Postgres identity検証に成功。 |
| AC-03 | L1 59 cycleでp95 1.043秒、max 1.754秒、fetch timeout/grid skip/status failure/error-code cycle/429は0。 |
| AC-04 | 直近2 cycleのready/freshは1177/1177、100%。 |
| AC-05 | candle logはreceived=stored=78,464、ignored/error 0、duplicate key 0。直近5分coverageはAster 99.812%、Bitget 100%、Hyperliquid 96.610%。 |
| AC-06 | Aster OI非null 0、Hyperliquidは177 instrumentを`oracle`として公開。 |
| AC-07 | commit p95 0.890秒、max 1.584秒。DB health 4 sampleでidle transaction、60秒超transaction、waiting/long lockはすべて0。 |
| AC-08 | CP-04のseeded real-Postgres integrationでrow count/key/timestamp/digest/SHA-256の100%照合を確認。shadowは完了UTC日を持たずarchive manifest 0であり、AC-08の代替証拠には使用しない。 |
| AC-09 | 旧leaseのraw 17,380行はsupersede後0、cleanup 0秒、orphan 0。TTL満了後の同一commandが新UUIDで再有効化し、book walkの3つの非保証flagを確認。 |
| AC-10 | 1440px/390pxの実画面とPast Note round-tripに成功。欠損・由来・参考限定disclaimerを表示し、売買推奨/裁定断定なし。 |
| AC-11 | 旧snapshot p95はbaseline 184秒、shadow 181秒、ratio 0.984。終端snapshot age 79/91秒は上限220.8秒以内。NRestarts 0、DuckDB opener 0..1。 |
| AC-12 | 自動raw投影の過小評価は棄却。DB growthを上限にした保守的必要量82.610GB < 開始時空き容量の75%である151.181GBでpass。 |
| AC-13 | 旧worktree/unit/DuckDB stateは変更せず稼働を継続。cutoverは未実施で、rollback資産を失っていない。 |

### CP-09 Final audit and cutover approval handoff — COMPLETE

証拠を提示し、push/merge/cutover/旧service停止は別の明示承認まで行わない。

Evidence: `sp-review`で最終diffを監査し、AllowedFiles外0、tracked/untracked whitespace 0、
conflict marker、secret、未接続debug、意図的test無効化の残存なしを確認した。DESIGN lintは
errors 0 / warnings 0。docs metadata/link testは17 passed、checkerは両方OK。cutoverは未承認・
未実施であり、CP-08/CP-09完了はその承認を代替しない。

## Minimal Verification

1. catalog/filter/provenance表形式test。
2. identity collision/multiplier表形式test。
3. 3種candle finality test。
4. disposable Postgresでmigration/dedupe/SCD2 integration test。
5. Parquet manifest/readback/prune integration test。
6. Web parser/componentと主要Playwright 1440px/390px。
7. Ruff check/format、Pyrefly、Web test/check/build、最終`verify-local.sh`を必要最小回数。

## Stop / Rollback

- Private/paid API、注文、秘密keyが必要。
- 必須値の意味・単位・finalityを推測する必要がある。
- rate limit、disk式、Postgres/Parquet照合、shadow既存影響のいずれかが不合格。
- JustPass資源へ接触する、または旧runtime/stateをcutover前に失う。
- 停止時は新shadowだけを止め、旧runtimeは無変更のまま残す。
- cutover承認後のrollbackは旧Web unitを復元し、旧scanner snapshotへ戻す。旧stateは自動削除しない。

## Evidence Log

- 2026-08-14: canonical worktreeはbranch `ai/scanner-cpu-snapshot-latency-p1-20260812-2333`、
  untracked `docs/perp-venue-universe-assessment-2026-08-14.md`のみ。変更しない。
- 2026-08-14: dedicated worktreeを`.ai-work/perp-universe`へ`origin/main@c4c68a9`から作成。
- 2026-08-14: existing `deploy-postgres-1`はJustPass所有、port 5432。再利用禁止。
- 2026-08-14: `/home/tn`は533GB中190GB空き、6 CPU、62GiB RAM。容量式はshadowで再計測する。
- 2026-08-14: CP-01 disposable Postgres migrationは初回1件、2回目0件、health ready。real-DB
  tests 6 passed。focused Ruff/Pyrefly passed。test containerは削除し、Venue API/live runtimeは未接触。
- 2026-08-14: CP-02 catalog/identity/storeを実装。fixture/identity tests、実Postgres SCD2/dedupe、
  Ruff/format/Pyrefly/diff-check passed。Bitget 754、Hyperliquid 232を1回だけ観測。AsterはCP-08待ち。
- 2026-08-14: CP-03 L1/candle runtimeを接続。deadline、missing-as-unavailable、candle finality、
  catalog-publish ordering、removed candle filtering、instrument version境界のfail-closed mappingを
  focused testと実Postgresで確認。liveは未操作。
- 2026-08-14: CP-04 Parquet readback/manifest generation/retentionを実Postgresで確認。rawの実schemaに合わせ、
  partition dropを1回最大10,000行のbounded DELETEへ限定変更した。

### Rejected shadow evidence

- `prep-watchdeck-market-evidence-20260814-2330`、`-2331`、`-2345`、
  `prep-watchdeck-market-evidence-20260815-0103`、`-0112`、`-0148`配下の先行runは、
  完了した15分baseline+60分shadowの受入証拠に使用しない。
- これらでは、`df`呼出しの互換性、Asterの公式REST hostとstartup candleの時間範囲、
  TTL後の同一command再有効化、`close_selection`のrow count読取時点、cleanup時のCompose停止を
  順に問題として検出し、修正後のfocused testへ分離した。中断または失敗したrunの
  一部周期を最終acceptanceへ合算していない。

### Accepted shadow evidence

- 受入runは
  `/home/tn/.local/share/prep-watchdeck-market-evidence-20260815-0153/20260814T165229Z-035b51e2`
  の1件だけ。15分baseline、60分shadow、exit 0、cleanup 0、自動summary pass、上記ACの
  手動照合まで完了した。
- `source-digest-before.txt`と`source-digest-after.txt`は
  `017a4240f45f2885412d2f5097121cb44d1e0486a0f14b0cba948202fd6fedb8`で一致した。このdigestは
  HEAD、tracked binary diff、untracked file hashを含み、shadow実行中のsource不変を証明する。
- 受入run後に、shadow harnessのraw容量投影と終端snapshot freshnessだけを修正し、
  関連test 8 passed。このpost-run harness-only差分とその後のplan/docs更新は上記digestの
  対象外であり、最終shadowで再実行済みとは扱わない。collector/Webのproduction runtime codeは
  受入run後に変更していない。
- 最終`sp-review`ではscope逸脱、whitespace、conflict、secret、debug、disabled testのblockerを
  検出せず、DESIGN lintとdocs gateも成功した。local実装はcutover承認待ちゲートへ到達した。
- commit、push、merge、live cutover、旧service停止は未承認・未実施。現行runtimeは継続稼働している。
