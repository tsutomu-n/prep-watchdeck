# Scanner Filter Templates

- 作成: `2026-06-18T04:43:28+09:00`
- 更新: `2026-08-12T21:38:47+09:00`
- 検証: `2026-08-12T21:38:47+09:00`
- 状態: `現行`

---

テンプレートは3つだけ。

```text
conservative
balanced
aggressive
```

4つ目は作らない。条件探しを増やさず、同じ分類思想で閾値だけを変える。

## 主な項目

- `universe`: スキャン対象に残す銘柄条件。BTCUSDTは対象外でもBTC比計算用に使う。
- `candles`: scanner判定に必要な5m足。現行値は4時間量倍率から導出した383本。
- detail chart source: filter設定から分離し、1,177本の5分足相当を維持する。
- `price_change`: surge と move の閾値。Changeだけでは監視対象にしない。
- `volume`: 自銘柄の普段比。current 15m は baseline に含めない。
- `turnover`: USDT売買代金。小さい急変は `NO_TRADE` 寄り。
- `roughness`: 15mの動きが直近5m一本に集中していないかを見る。`aggressive` はlive確認で監視対象が
  出やすいよう、他templateより緩め。
- `data_quality`: 5m grid の欠損率、欠損本数、ゼロ出来高比率を評価し、dataQuality = PARTIAL 等に反映（MVP で活性化済み）。
- `btc_relative`: BTC連動か、ALT個別の強弱かを見る。
- `funding`: funding過熱の注意タグ。
- `open_interest`: tickerの `holdingAmount` を比較する。
- `category`: WATCH/CAUTION/NO_TRADE/LOW_PRIORITY の境界。`min_attention_score_for_display` は表示対象の最低 attention score。

## data quality

```toml
[data_quality]
min_coverage_ratio = 0.98
max_missing_bar_count = 2
warn_zero_volume_bar_ratio = 0.15
```

- `min_coverage_ratio`: 期待 5m grid に対する有効足最低比率。これ未満なら dataQuality=PARTIAL 寄り。
- `max_missing_bar_count`: 欠損許容数。これ超で PARTIAL。
- `warn_zero_volume_bar_ratio`: ゼロ出来高比率の警告閾値（現在は出力値として利用、分類影響小）。
