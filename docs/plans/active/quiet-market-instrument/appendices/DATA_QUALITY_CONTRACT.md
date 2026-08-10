# Data Quality 表示契約

- 作成: `2026-08-10T22:18:28+09:00`
- 更新: `2026-08-10T23:24:00+09:00`
- 検証: `2026-08-10T23:24:00+09:00`
- 状態: `実装計画`

---

## 決定

Data qualityは内部判断として維持する。正常時の表示は削除し、異常時だけユーザーが行動できる具体語を表示する。

| 内部状態 | 表示 | Candidate | Watchlist |
|---|---|---|---|
| OK | 非表示 | 既存契約どおり | 表示可 |
| PARTIAL | 一部データ不足 | 今回は現行可否を保持。ranking metricが`None`なら既存契約で除外 | 表示可 |
| STALE | 更新遅延 | 除外 | 表示可、警告必須 |
| MISSING / その他 | 判定不能 | 除外 | 表示可、警告必須 |

## 実装原則

- 現行`dataQuality -> riskTag -> category -> ranking`を先に追う。
- 既存`NO_TRADE`除外で成立するなら新gateを追加しない。
- PARTIAL専用の新しいfield-level gateは今回作らない。
- 色だけでは伝えない。
- technical enumをそのまま出さない。
- 正常な`OK`を非表示にしても、Topbarのsource/service/data freshness契約は維持する。
