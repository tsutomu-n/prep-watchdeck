# 04 74h Candidate契約

- 作成: `2026-08-09T15:39:47+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---


## 完成契約

### Input

- closed 5分足
- current close
- 74h前anchor close
- current 24h quote turnover
- 74h前に終了するhistorical 24h quote turnover
- config thresholds

### Output

```text
price_condition_matched: bool | null
turnover_condition_matched: bool | null
user_rule_74h_matched: bool | null
```

### Truth table

| Price | Turnover | Composite |
|---|---|---|
| True | True | True |
| True | False | False |
| False | True | False |
| False | False | False |
| None | any | None |
| any | None | None |

`None`は比較不能であり、未達とは別。

## Reference implementation shape

```python
price_match: bool | None
turnover_match: bool | None

if insufficient_history:
    price_match = None
    turnover_match = None
elif historical_turnover <= 0:
    price_match = abs(price_change_pct) >= price_threshold
    turnover_match = None
else:
    price_match = abs(price_change_pct) >= price_threshold
    turnover_match = turnover_change_pct >= turnover_threshold

matched = (
    None
    if price_match is None or turnover_match is None
    else price_match and turnover_match
)
```

## Candidate gate

Candidateのtimeframe rankingだけを次でfilterする。

```python
candidate_source = [
    row
    for row in rows
    if row.user_rule_74h_matched is True
]
```

さらに現行の`NO_TRADE`除外を適用する。

### 保持するもの

- snapshot `rows`: 全監視row
- Watchlist: 全監視row
- Raw Sort: 現行通り
- Smart Rank: 現行通り
- `rankings.noTrade`: 全rowから生成する既存診断

### 変えるもの

- Candidate sectionの4 ranking母集団だけ

## Reason codes

```text
USER_74H_PRICE_MATCH
USER_74H_VOLUME_MATCH
```

片方だけ達成したrowにも、達成した側のreason codeを付ける。これによりWatchlist/Selected detailで、Candidate未達の理由を再構築できる。

## UI文言

Candidateに、少なくとも次の意味を表示する。

```text
74h条件合致の候補
価格±4%以上 かつ 24h売買代金+15%以上。履歴不足は候補に含めません。
```

閾値はtemplateで変わり得るためUIへhardcodeしない。snapshot summaryへ次を出し、Webは局所validationして表示する。

```json
{
  "candidateRule74h": {
    "operator": "AND",
    "priceAbsPct": 4.0,
    "turnoverIncreasePct": 15.0,
    "turnoverMode": "current_24h_vs_74h_ago_24h"
  }
}
```

summaryが欠損・不正なら数値を推測せず、「74h価格条件かつ74h売買代金条件」と一般表示する。

## Version

- `rulesetVersion`: `2` → `3`
- `featureVersion`: OI変更と同時に `2` → `3`
- `schemaVersion`: 変更なし
