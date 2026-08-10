# 出来高倍率・活動phase契約

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 出来高倍率

```text
ratio(tf) = current turnover(tf) / median(previous rolling turnover(tf))
```

| TF | 5m bar数 | 表示 |
|---|---:|---|
| 15m | 3 | Watchlist + Inspector |
| 1h | 12 | Inspector |
| 4h | 48 | Inspector |

baseline候補数とfloorは既存`volume`設定を再利用する。15mの既存値は変更しない。

## Activity phase

| 内部値 | 表示 | 条件概要 |
|---|---|---|
| BURST | 急増 | 15mがstrong、1hがmin未満 |
| EXPANDING | 拡大 | 15m・1hがmin以上、4hがmin未満 |
| SUSTAINED | 持続 | 1h・4hがmin以上 |
| COOLING | 失速 | 15mが1.0未満、かつ1hまたは4hがmin以上 |
| NORMAL | 平常 | 上記以外 |
| UNKNOWN | 判定不能 | いずれか欠損・非有限 |

優先順は`UNKNOWN -> COOLING -> SUSTAINED -> EXPANDING -> BURST -> NORMAL`。

Activity phaseは価格方向、売買推奨、Scoreを意味しない。Watchlistでは`NORMAL / 平常`を表示せず、Inspectorでは全状態を表示する。
