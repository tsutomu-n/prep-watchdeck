# Scanner Filter Templates

- 作成: `2026-06-18T04:43:28+09:00`
- 更新: `2026-06-29T20:31:00+09:00`
- 検証: `2026-07-16T23:22:53+09:00`
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
- `candles`: 5m足と必要本数。74h変化率と比較用24h窓のため `min_required_bars >= 1177`。
- `user_rule`: 74hの価格変化または出来高増加を計算し `userRule74hMatched` として出力（閾値は compute で使用）。
- `price_change`: surge と move の閾値。Changeだけでは候補にしない。
- `volume`: 自銘柄の普段比。current 15m は baseline に含めない。
- `turnover`: USDT売買代金。小さい急変は `NO_TRADE` 寄り。
- `roughness`: 15mの動きが直近5m一本に集中していないかを見る。`aggressive` は live 確認で候補が出やすいよう、他 template より緩め。
- `data_quality`: 5m grid の欠損率、欠損本数、ゼロ出来高比率を評価し、dataQuality = PARTIAL 等に反映（MVP で活性化済み）。
- `btc_relative`: BTC連動か、ALT個別の強弱かを見る。
- `funding`: funding過熱の注意タグ。
- `open_interest`: tickerの `holdingAmount` を比較する。
- `category`: WATCH/CAUTION/NO_TRADE/LOW_PRIORITY の境界。`min_attention_score_for_display` は表示対象の最低 attention score。
- `ranking`: main ranking 件数と `NO_TRADE` 除外設定。現行 snapshot ranking 生成では `top_n` が表示上限として反映され、`NO_TRADE` 除外は実装上維持されています。

## 74h user rule

現行テンプレートは次の rule を持ちます。

```toml
[user_rule]
price_74h_abs_pct = 4.0
volume_74h_mode = "current_24h_vs_74h_ago_24h"
volume_74h_min_increase_pct = 15.0
```

- `price_74h_abs_pct`: 74h 価格変化で userRule74hMatched を true にする閾値（compute_74h_features で使用）。
- `volume_74h_mode`: 現在24h売買代金と、74h前で終わる24h売買代金を比較（固定モード）。
- `volume_74h_min_increase_pct`: 比較元24hに対する現在24hの増加率閾値（userRule74hMatched 計算で使用）。

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

## ranking 設定の現在位置

各 template には次があります。

```toml
[ranking]
exclude_no_trade_from_main_rankings = true
top_n = 10
```

現行の main ranking は `apps/scanner-core/src/prep_watchdeck/domain/screening/rankings.py` 側の builder が生成し、template の `ranking.top_n` を表示上限として使います。`NO_TRADE` 除外は維持され、ranking metadata の `totalEligible` も `NO_TRADE` 除外後かつ対象 metric 値がある銘柄数です。

このため、template docs では `ranking` を「ranking 表示上限と NO_TRADE 除外方針の現在値」として扱います。
