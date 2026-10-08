# Prep Watchdeck Attention Core 設計仕様 v1.0

timestamp="2026-10-08(木)_23:47 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-08T23:47:49+09:00`
- 状態: `実装計画`


> 対象Repository: `tsutomu-n/prep-watchdeck`  
> 読者: Codex / coding agent  
> 作成日: `2026-10-08`  
> 調査基準: `main@4278d8a690141a5118cc150b7f39f9f4d13822fd`  
> 状態: 実装前設計  
> 実装許可の意味: 本書は設計・計画であり、production service、live DB、systemd unit、外部Providerへの実通信、deploy、cutoverを自動的に許可しない。

---

## 1. 目的

Prep Watchdeckへ、既存のMarket Core、独立Ranking Core、Selected market laneを壊さずに、次の能力を追加する。

1. 市場全体から「今、人間が確認する価値が高い対象」を抽出する。
2. momentum、activity、positioning、cross-Venue dislocationを別々のcomponentとして説明可能にする。
3. scoreとdata quality/confidenceを分離する。
4. candidate rankingを、後知恵や大量探索による偶然のwinnerから区別して検証する。
5. 将来、限られたdepth/trade capture枠を配分するためのshadow hot-setを作る。
6. manual selectionを維持し、自動注文・資金移動へ接続しない。

完成像は次である。

```text
全市場を低コストで観測
        ↓
Attention Coreでcomponent別に優先順位化
        ↓
上位候補・理由・品質を人間へ表示
        ↓
shadow hot-setで配分方法を検証
        ↓
十分な証拠と容量確認後だけ限定captureへ進む
```

---

## 2. 現行Repositoryで保全する事実

### 2.1 Market Core

`apps/market-core`は以下を既に持つ。

- 3 Venue: Bitget / Hyperliquid Core / Aster
- SCD2 instrument version
- conservative identity grouping
- Catalog / L1 / candle / funding / OI
- `market_state_1m`
- `candle_1m`
- selected depth/trades
- book walk
- Recovery / Audit
- Postgres + confirmed Parquet archive
- schema validated atomic JSON artifacts
- `market-metrics.json`のread-only projection
- missing / stale / partial / invalidの明示

新しいAttention機能はMarket Coreのwriter責務へ混ぜない。

### 2.2 Ranking Core

`apps/ranking-core`は以下を既に持つ。

- Bybit / Binanceの固定reference map
- mapping evidence、contract revision
- 確定1分足
- 共通cutoffのimmutable generation
- 15m / 1h / 24h / dailyのreturnとquote turnover
- turnover ratio
- JST day range position
- rank change
- source outage / history missing / generation gap / map changeの区別
- loopback read API
- 専用SQLiteとstate root
- 約48時間のbounded minute history

Ranking Coreは堅牢なreference-market scannerであり、現状のrankは主にreturnまたはturnoverの単一軸sortである。Attention Coreはこれを置換しない。

### 2.3 Web

現行Webは次の意味を既に持つ。

- Ranking rowの`originals`とUniverseのinstrument ID/versionを厳密に照合できる。
- favorites、saved views、recent markets、Past Noteがある。
- Market artifact、market metrics、ranking responseをschema検証する。
- staleなvalidated snapshotを表示する場合は更新停止として扱う。
- `ReferenceMarkets.svelte`は既に大きいため、新しいAttention UIを同componentへ押し込まない。

### 2.4 Selected market

現行selected laneは次を持つ。

- single active selection
- 500ms debounce
- 15分TTL
- 5分heartbeat
- cleanup deadline
- depth/trade queue writer
- group membership再確認
- atomic local command

このlaneは将来のhot-slot実装に利用できるが、初版でmulti-selectionへ変更しない。

---

## 3. 比較した設計案

### 案A: Ranking CoreへAttentionを追加

**利点**

- 既存のimmutable generationを直接利用できる。
- loopback APIとSQLiteを再利用できる。
- 最短実装量は小さい。

**欠点**

- Ranking Coreは外部reference市場から独立していることが重要な設計理由である。
- Funding、OI、spread、native cross-Venue dataを取り込むと独立性が崩れる。
- 48時間保存では長期検証が不足する。
- ranking source failureとnative source failureの境界が曖昧になる。

**判定**

採用しない。

### 案B: 新しい`apps/attention-core`を追加

**利点**

- Market CoreとRanking Coreのfailureを伝播させない。
- 両Coreをread-only inputとして扱える。
- feature、candidate policy、evidence、shadow allocationを独立して版管理できる。
- 将来MLを追加してもingestion責務を汚さない。
- Attentionのstorage、schema、API、validationを明確に分離できる。

**欠点**

- 新package、state root、schema、API、検証gateが必要。
- input generation間の時刻差を正しく扱う必要がある。
- 新しい運用surfaceが増える。

**判定**

採用する。

### 案C: Webだけで合成scoreを計算

**利点**

- 最小の変更で画面表示できる。
- user preference overlayを扱いやすい。

**欠点**

- Browserごとに結果が変わり得る。
- 長期証拠を保存できない。
- backtest、candidate family、shadow allocationへ進めない。
- Provider/DB failureの意味を十分に固定できない。
- Browser表示中だけ計算するため研究母集団が偏る。

**判定**

採用しない。

---

## 4. 採用アーキテクチャ

```text
Market Core state
  ├─ artifacts/universe-snapshot.json
  ├─ artifacts/service-state.json
  └─ artifacts/market-metrics.json
             │ read-only
             │
Ranking Core loopback API
  └─ /rankings canonical query
             │ read-only
             ▼
      apps/attention-core
        ├─ stable input readers
        ├─ exact identity join
        ├─ raw feature generation
        ├─ component policies
        ├─ current attention generation
        ├─ prospective evidence store
        ├─ outcome settlement
        ├─ candidate-family validation
        └─ shadow hot-set allocator
             │
             ├─ loopback API :8770
             ├─ dedicated state root
             └─ immutable artifacts
                    │
                    ▼
               SvelteKit Web
                 /attention
```

### 4.1 State root

環境変数:

```text
PREP_WATCHDECK_ATTENTION_STATE_DIR
```

既定:

```text
~/.local/share/prep-watchdeck-attention
```

Market state、Ranking state、Repo内`var/`と同一または内包関係を拒否する。

### 4.2 Port

既定loopback port:

```text
8770
```

1024未満、Market DB `55432`、通常Postgres `5432`、Ranking `8769`を拒否する。

### 4.3 外部通信

Attention Core自身はProviderへ接続しない。

許可するinput:

- Market Coreが発行したlocal files
- Ranking Coreのloopback `/rankings`
- 将来追加する明示的なoffline fixture

Attention APIのreadで外部取得を開始しない。

---

## 5. Input generation

### 5.1 canonical Ranking query

Attention CoreはRanking Coreへ毎generationにつき1回だけ問い合わせる。

```text
period=15m
dailyReferenceJst=00:00
order=turnover
minTurnover=0
```

理由:

- `RankingResponse.rows`には15m / 1h / 24h / dailyの全windowが含まれる。
- `turnoverRatios`と`dayRangePosition`も含まれる。
- query違いでProvider取得は増えないが、1回で必要inputを固定できる。
- Attention CoreはRanking Coreのserver rankを最終Attention rankとして再利用しない。

### 5.2 Market artifact read

次を読む。

```text
universe-snapshot.json
service-state.json
market-metrics.json
```

Market artifact bundleは`service-state`をread前後に読み、同じ`generatedAt`であることと、必要artifactのfile stateが`ready`で対応する時刻を持つことを確認する。

`market-metrics.json`は独立laneなので、regular file identityをread前後で比較する。破損、未知schema、read途中変更を欠測の成功値へ変換しない。

### 5.3 時刻の扱い

異なるinput laneを同一cutoffだったことにしない。

各generationで保持する。

```text
decisionAt
rankingCutoff
rankingGeneratedAt
rankingGenerationId
rankingMapVersion
rankingMetricVersion

universeGeneratedAt
serviceGeneratedAt

marketMetricsGenerationId
marketMetricsGeneratedAt
marketMetricsCandleCutoff
```

全featureは自身のsource/end/observed時刻を保持する。

`decisionAt`より後の値は拒否する。

複数laneの時刻差は`inputSkewSeconds`として保存し、scoreのconfidenceとは別に表示する。

---

## 6. Identity join

Attention asset identityはRanking `MappingRow.id`を正本にする。

native instrument joinは次のtupleで行う。

```text
(original.instrumentId, original.versionId)
==
(universe.venueInstrumentId, universe.venueInstrumentVersionId)
==
(marketMetrics.venueInstrumentId, marketMetrics.venueInstrumentVersionId)
```

禁止:

- symbol文字列だけのjoin
- base assetだけのjoin
- version違いの履歴連結
- mapping review行への価格補完
- current Universeにない旧originalを別契約で補う

初期対象:

```text
mappingStatus == verified
AND reference != null
AND current original match >= 1
```

`unsupported`、`review`、`out_of_scope`は入力記録へ残してよいが、scoreを作らない。

---

## 7. Internal feature contract

### 7.1 RawFeatureValue

```text
value: float | null
status:
  ready
  missing
  stale
  invalid
  unsupported
reason: string | null
unit: string | null
source: string
startAt: timestamp | null
endAt: timestamp | null
observedAt: timestamp | null
```

0は観測値として保存する。欠測を0へ変換しない。

### 7.2 FeatureSnapshotRow

最低限:

```text
assetId
asset
referenceKey
originalInstrumentVersions
decisionAt
qualityReasons

referenceReturn15m
referenceReturn1h
referenceReturn24h
referenceTurnover15m
referenceTurnover1h
referenceTurnoverRatio15m
referenceTurnoverRatio1h
referenceDayRangePosition

nativeReturn15mMedian
nativeReturn1hMedian
oiChange15mMedian
oiChange1hMedian
fundingAbsMaxPerHour
fundingRangePerHour
spreadMedianBps
spreadMaxBps
markDispersionBps

freshNativeVenueCount
readyNativeVenueCount
```

### 7.3 注意

現行`market-metrics.tradeChange`は、名称に`trade`を含むが**確定1分足closeの変化率**であり、売買代金変化ではない。Activityへ誤投入しない。

現行`volume24hRaw`はsource unitを保持する。unitが比較可能と確認されない限りcross-Venue合成scoreへ入れない。

---

## 8. Cross-Venue feature

### 8.1 mark dispersion

freshなUSD-like native marksが2 Venue以上ある場合だけ:

\[
dispersionBps =
10000 \times \frac{\max(mark)-\min(mark)}{median(mark)}
\]

これはreference indicatorであり、裁定可能spreadや約定利益と表示しない。

### 8.2 funding

freshな`fundingRatePerHour`から:

```text
fundingAbsMaxPerHour = max(abs(values))
fundingRangePerHour = max(values) - min(values)
```

### 8.3 spread

各Venue:

\[
spreadBps =
10000 \times \frac{ask-bid}{(ask+bid)/2}
\]

`bid <= 0`、`ask < bid`、stale L1はinvalid/unavailable。

### 8.4 OI

`market-metrics.oiChange`の`unit=base`かつ`availability=available`のみ対象。

2 Venue以上ならmedian、1 Venueならsingle-source featureとして保持する。1 Venueをcross-Venue consensusと呼ばない。

---

## 9. Component policies

初版はcomponentを混ぜずに公開する。

```text
movement
activity
positioning
dislocation
```

`confluence`は4 componentが全てreadyの場合だけ作る。

### 9.1 Cross-sectional percentile

generation内のready raw valueについてmidrank percentileを使う。

- stable sort key: `(rawValue, assetId)`
- 同値は平均rank
- `0..100`
- peer数がpolicyの`minimumPeers`未満なら`insufficient_peers`
- default `minimumPeers=20`
- NaN / Infinityは拒否

### 9.2 movement-v1

raw:

```text
max(abs(referenceReturn15m), abs(referenceReturn1h))
```

direction:

- rawを決めたwindowのreturn符号
- 同値なら15mを優先
- `up / down / flat / unknown`

### 9.3 activity-v1

raw:

```text
max(referenceTurnoverRatio15m, referenceTurnoverRatio1h)
```

両方欠測ならunavailable。

### 9.4 positioning-v1

raw候補:

```text
abs(oiChange15mMedian)
abs(oiChange1hMedian)
abs(fundingAbsMaxPerHour)
```

ready候補のmax。

### 9.5 dislocation-v1

raw候補:

```text
markDispersionBps
abs(fundingRangePerHour)
spreadMaxBps
```

ready候補のmax。

### 9.6 confluence-v1

4 component scoreが全てreadyの場合:

\[
confluence = mean(movement, activity, positioning, dislocation)
\]

欠けたcomponentを0として平均しない。

### 9.7 scoreとquality

別fieldにする。

```text
score: 0..100 | null
componentStatus
readyComponentCount
totalComponentCount=4
coverageRatio
qualityReasons
```

high scoreをhigh confidenceと呼ばない。

---

## 10. User overlay

favorites、saved views、recent markets、Past Noteをmarket scoreへ混ぜない。

Web表示時だけ別のpriority軸にできる。

```text
marketAttentionRank
userPriority:
  favorite
  pinned
  recentlyViewed
```

市場scoreの再現性を維持する。

---

## 11. Runtime generationとevidence cadence

### 11.1 Current generation

毎分、Ranking generation更新後にinputを固定しcurrent Attention responseを作る。

APIはcurrent generationを返すだけで、read時に再計算しない。

### 11.2 Prospective evidence

長期証拠は5分境界だけ保存する。

理由:

- 1分ごとの重複outcomeを減らす。
- storage量を抑える。
- 15m/60m outcomeに対して十分な発見頻度を持つ。
- current UIは1分更新を維持できる。

### 11.3 Dedicated SQLite

初版は専用`attention.sqlite3`を使用する。

最低限のtable:

```text
input_generations
feature_rows
component_rows
outcome_rows
candidate_policies
candidate_runs
shadow_allocations
```

- WAL
- single writer
- immutable generation identity
- transaction batch insert
- schema version metadata
- foreign keys enabled
- data root escape拒否
- symlink拒否
- DB writerはAttention Coreのみ

production retentionは実測前に固定しない。初版developmentでは削除しない。容量観測をreportし、archive/retention taskを別checkpointにする。

---

## 12. Outcome settlement

AttentionはPnLをprimary truthにしない。

### 12.1 Primary opportunity outcome

Ranking referenceの確定1分足を使い、snapshot後のhorizonで:

```text
futureMaxAbsReturn15m
futureMaxAbsReturn60m
futureCloseReturn15m
futureCloseReturn60m
timeToTopDecileMove
```

input cutoff以前のbarをoutcomeへ使わない。

### 12.2 Secondary outcome

native laneが完全な場合:

```text
futureNativeDispersionMax15m
futureNativeDispersionMax60m
futureOiChangeAbsMax60m
```

別outcome familyとして扱う。

### 12.3 Pending

horizonが完了していない、bar欠損、contract revision変更、map changeは`pending`または`unscorable`。0へ変換しない。

---

## 13. Candidate validation

### 13.1 Candidate family

policyを結果を見る前にfreezeする。

例:

```text
reference-abs-return-15m
reference-abs-return-1h
movement-v1
activity-v1
positioning-v1
dislocation-v1
confluence-v1
```

candidate追加はnew family/version。

### 13.2 Baselines

最低限:

```text
absolute 15m return
absolute 1h return
turnover ratio
```

現行Rankingのgainers/losers/turnoverを「Attentionの最終baseline」と一括せず、目的別に比較する。

### 13.3 Evaluation metrics

Kはpolicyで固定する。初版:

```text
K = 10
K = 20
```

保存:

```text
future-opportunity Recall@K
Precision@K against realized top decile
NDCG@K
mean future max absolute return
median lead time
coverage
unscorable rate
rank/set churn
```

### 13.4 Dependence

minute rowsを独立sampleとしない。

評価単位はUTC day blockをprimary、6-hour blockをsensitivityとする。

overlapping horizons、同asset連続signal、共通market shockを理由にiid testを使わない。

### 13.5 Multiple testing

candidate family全体へjoint block resamplingを使う。

初版実装名:

```text
attention-family-max-t-v1
```

White Reality Check、SPA、Romano-Wolfのpaper exact implementationとは呼ばない。

### 13.6 Power / MDE

`not_supported`と`not_estimable`を分離する。

report:

```text
blockCount
effectiveDays
minimumPracticalDelta
estimatedPower
MDE80
decision
reasons
```

---

## 14. Shadow hot-set

実streamを増やす前に、desired setだけを保存する。

### 14.1 manual selection

manual selectionはAttentionから変更しない。

```text
manual selection = pinned user lane
shadow hot-set = recommendation only
```

### 14.2 Baseline allocators

初版は3方式。

1. `top-k-v1`
2. `hysteresis-v1`
3. `cost-aware-greedy-v1`

### 14.3 top-k-v1

毎generationの上位K。

### 14.4 hysteresis-v1

policy:

```text
K
entryRank <= K
exitRank > K + buffer
minimumHoldMinutes
```

初期値をコードへ隠さずpolicy artifactへ保存する。

### 14.5 cost-aware-greedy-v1

benefit:

```text
normalized attention score
```

cost:

```text
added groups
removed groups
minimum hold violation
estimated warm-up cost
```

実測前は`estimated`と明示する。

### 14.6 k-server

k-serverを初版へ入れない。

導入条件:

- transition costを実測できる。
- costがmetricとして扱えるか検査する。
- 非対称costならmetric k-serverの保証を主張しない。
- top-K/hysteresis/cost-aware baselineより改善を示す。

### 14.7 k-median / k-medoids

代表市場panelには利用候補。

Attention上位選択と混ぜない。

用途:

```text
coverage regression panel
代表銘柄dashboard
feature-space監視
```

---

## 15. Actual captureへのgate

次を全て満たす前にmulti-captureを実装・有効化しない。

1. prospective evidenceが最低評価期間を満たす。
2. candidate family補正後にbaseline改善を確認する。
3. churn/cost guardrailを満たす。
4. selected streamのsubscribe/unsubscribe/first-event時間を隔離環境で計測する。
5. Provider connection/subscription上限を再受入する。
6. Market Core writer、queue、Postgres、artifact latencyへの影響を確認する。
7. manual selectionを失わない設計を確定する。
8. rollbackを実証する。

将来commandは現行`selection.json`を黙ってv2化せず、別contractを使う。

候補:

```text
control/attention-hotset.json
```

現行single selection contractは維持する。

---

## 16. UI

### 16.1 route

新規:

```text
/attention
```

現行`ReferenceMarkets.svelte`へ追加しない。

### 16.2 first UI

- component tab
- Attention rank
- asset
- direction context
- score
- ready component count
- quality/freshness
- reason
- native/reference detailへのlink
- candidate policy version
- data-as-of

### 16.3 禁止

- scoreを利益確率と表示
- high rankを注文指示と表示
- unavailableを0表示
- qualityを色だけで表示
- favoritesをmarket scoreへ混入
- current Attention readでProvider callを発生

---

## 17. Failure policy

### 17.1 Ranking unavailable

current response:

```text
status=unavailable
reason=ranking_unavailable
```

古いrankingをfreshとして再利用しない。

### 17.2 Market bundle changed during read

再読1回。再び変化したらgeneration作成を拒否。

### 17.3 Market metrics missing

native positioning/dislocationをpartial/unavailableにする。reference movement/activityは計算可能。

### 17.4 Input map/version mismatch

該当assetをinvalidにし、別versionで補完しない。

### 17.5 DB write failure

current generationをmemory/publicへ先に発行しない。

transaction成功とreadback後にpublishする。

### 17.6 Outcome correction

既存outcomeを上書きせずeditionを追加し、古いevaluation reportをstaleにする。

---

## 18. Security / operational boundary

- loopback-only API
- request body上限
- no arbitrary URL
- no external credential
- no Market/Ranking DB writer
- no secret in logs/artifacts
- state root isolation
- production unit install/start/restartは別承認
- no automatic trading
- no automatic Binding/selection change
- systemd templateはruntime acceptance後

---

## 19. Rollback

Foundation段階:

```text
attention-core processを停止
Webの/attention linkを外す
Market Core / Ranking Coreは無変更で継続
```

Shadow段階:

```text
shadow policy発行を停止
manual selectionは無変更
```

Actual capture段階は別Decisionとrollback planを要求する。

---

## 20. 実装段階

```text
F0 Repository contract / package skeleton
F1 Stable input readers
F2 Exact identity join / raw feature snapshot
F3 Component policies / current API
F4 Prospective evidence storage
F5 Outcome settlement / validation
F6 Web Attention surface
F7 Shadow hot-set
F8 Capacity / live acceptance
F9 Actual capture decision
```

F0〜F7はproduction captureを増やさず実装できる。

---

## 21. 成功条件

この改良の成功は「複雑なscoreを追加した」ことではない。

成功条件:

1. 同じinput generationから同じAttention結果を再現できる。
2. scoreとqualityを分離できる。
3. exact identity/versionでのみcross-surface joinできる。
4. candidate探索数を隠さず検証できる。
5. outcome未完成・欠損・訂正を正しく扱える。
6. shadow allocatorの発見力とchurn/costを比較できる。
7. manual selectionと既存runtimeへ影響を与えない。
8. 証拠不足なら`not_estimable`を返せる。
9. actual captureへ進む前に停止できる。
