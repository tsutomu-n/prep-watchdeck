# 付録C コード変更ブループリント

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 1. LongHorizonFeatures

推奨形:

```python
@dataclass(frozen=True)
class LongHorizonFeatures:
    price_change_74h_pct: float | None
    turnover_current_24h_usdt: float | None
    turnover_24h_ending_74h_ago_usdt: float | None
    volume_change_74h_24h_pct: float | None
    price_condition_matched: bool | None
    turnover_condition_matched: bool | None
    user_rule_74h_matched: bool | None
```

既存consumerがpositional constructionをしている場合は、全call siteを同時更新する。keyword constructionへ寄せる大規模refactorはしない。

## 2. Reason codes

```python
reason_codes = [row.label]
if long_horizon.price_condition_matched is True:
    reason_codes.append("USER_74H_PRICE_MATCH")
if long_horizon.turnover_condition_matched is True:
    reason_codes.append("USER_74H_VOLUME_MATCH")
```

順序はstableにする。

## 3. Ranking API

推奨contract:

```python
def build_rankings(
    rows,
    top_n: int,
    *,
    exclude_no_trade: bool = True,
    require_user_rule_74h: bool = False,
):
    all_rows = list(rows)
    source = all_rows
    if require_user_rule_74h:
        source = [row for row in source if row.user_rule_74h_matched is True]
    if exclude_no_trade:
        source = [row for row in source if row.category != "NO_TRADE"]

    # timeframe rankings from source
    # noTrade diagnostic from all_rows
```

既存builderの型に合わせて命名を調整してよいが、all rowsとranking sourceを混同しない。

## 4. Candidate rule summary

```python
snapshot.summary["candidateRule74h"] = {
    "operator": "AND",
    "priceAbsPct": config.user_rule.price_74h_abs_pct,
    "turnoverIncreasePct": config.user_rule.volume_74h_min_increase_pct,
    "turnoverMode": config.user_rule.volume_74h_mode,
}
```

Webは数値・operator・modeを局所validationし、不正時はgeneric textへfallbackする。

## 5. OI sample record

```python
@dataclass(frozen=True)
class OpenInterestSampleRecord:
    symbol: str
    bucket_ts_ms: int
    holding_amount: float
    source_ts_ms: int
    updated_at_ms: int
```

Pydantic modelを使用する既存規約なら、それに合わせる。

## 6. OI application helper

```python
FIVE_MINUTES_MS = 5 * 60 * 1000
OI_RETENTION_MS = 24 * 60 * 60 * 1000


def oi_bucket(ts_ms: int) -> int:
    return ts_ms - ts_ms % FIVE_MINUTES_MS


def build_previous_oi_map(current_tickers, samples, lookback_minutes):
    by_key = {(s.symbol, s.bucket_ts_ms): s.holding_amount for s in samples}
    result = {}
    lookback_ms = lookback_minutes * 60_000
    for ticker in current_tickers:
        if not valid_oi(ticker.holding_amount) or ticker.ts_ms <= 0:
            continue
        target = oi_bucket(ticker.ts_ms) - lookback_ms
        previous = by_key.get((ticker.symbol, target))
        if valid_oi(previous):
            result[ticker.symbol] = previous
    return result
```

実際には既存model field名へ合わせる。

## 7. Store API

推奨minimum:

```python
def upsert_open_interest_samples(self, samples: list[OpenInterestSampleRecord]) -> None: ...
def load_open_interest_samples(self, start_ts_ms: int, end_ts_ms: int) -> list[OpenInterestSampleRecord]: ...
def delete_open_interest_samples_before(self, cutoff_ts_ms: int) -> int: ...
```

1 snapshot cycleにつき一括write・一括read・一括prune。N+1 query禁止。

## 8. Service snapshot order

```text
load tickers
→ build valid current samples
→ upsert current samples
→ load target range once
→ build previous_oi_by_symbol
→ prune old samples
→ build_scanner_rows(previous_oi_by_symbol=...)
→ publish snapshot
```

upsert後にtarget rangeを読む。current bucketはtarget bucketと異なるため、自己比較にならない。

## 9. UI

```svelte
<div>
  <dt>OI 60分</dt>
  <dd>{openInterestStateLabel(row.openInterestState)}</dd>
</div>
```

Watchlist rowには追加しない。
