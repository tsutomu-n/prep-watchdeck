# 05 OI 60分変化 契約

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 目的

`change_lookback_minutes = 60` を、実在するlocal historyへ接続する。

## Storage contract

```sql
CREATE TABLE IF NOT EXISTS open_interest_samples (
  symbol TEXT NOT NULL,
  bucket_ts_ms BIGINT NOT NULL,
  holding_amount DOUBLE NOT NULL,
  source_ts_ms BIGINT NOT NULL,
  updated_at_ms BIGINT NOT NULL,
  PRIMARY KEY (symbol, bucket_ts_ms)
);
```

## Sampling

- source: `ticker_latest.holding_amount`
- source timestamp: ticker自身の`ts_ms`
- bucket: `floor(ts_ms / 300000) * 300000`
- interval: 5分
- same bucket: latest valid sampleでupsert
- valid OI: finite and >0
- freshness: ticker source/local updateが既存のfreshness上限内であること。stale current OIはsampleしない
- retention: 24時間
- prune: snapshot cycle内でbounded delete

5分bucketを採用する理由:

- 60分変化に十分な分解能
- 1分保存よりwrite/row数を5分の1へ削減
- service snapshotが60秒周期でも同一bucket upsertで増殖しない

## Reference lookup

```text
current_bucket = floor(current_ticker_ts / 5m) * 5m
target_bucket = current_bucket - lookback_minutes * 60_000
```

- exact target bucketのみ採用
- targetなし → UNKNOWN
- current tickerがstale/invalid → sampleせずUNKNOWN
- nearest value、線形補間、直近値代用は禁止
- per-symbol queryは禁止。一括loadしてmap化する

## Classification

既存thresholdを使用する。

```text
change_pct = (current / previous - 1) * 100
>= +3%  -> INCREASING
<= -3%  -> DECREASING
otherwise -> STABLE
missing/invalid -> UNKNOWN
```

## Attention Score

現行weight構造を維持するが、`UNKNOWN` fallbackは0とする。

```python
oi_score = {
    "INCREASING": 1.0,
    "STABLE": 0.5,
    "DECREASING": 0.3,
}.get(open_interest_state, 0.0)
```

UNKNOWNが2点相当を得る現行fallbackは廃止する。

## Upgrade behavior

- upgrade直後は60分前sampleがないためUNKNOWN。
- 60分以上の継続sampling後に判定可能になる。
- external backfillはしない。
- restart後はDuckDB sampleを再利用する。
- downtimeでtarget bucketがない場合はUNKNOWNへ戻る。

これは障害ではなく、正しいfail-closed動作。

## Retention / capacity

最大500 symbols想定でも、5分bucket×24hは約144,000 rows。無期限保持しない。

## Transaction / lock

- 既存DuckDB storeのconnection/lock/transactionを使用する。
- snapshot layerから独立connectionを開かない。
- sample upsert、reference load、pruneの順序とtransaction境界はstore側に閉じる。
- 同じDBへ複数writerを許可しない現行契約を維持する。
