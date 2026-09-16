# prep-watchdeck 現行概要

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-16T21:23:15+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## 製品の役割

`prep-watchdeck`は、裁量トレーダーが市場から注目対象を発見し、分析し、比較し、最終判断を行うための
local-first market intelligence workspaceである。

Repositoryの現行surfaceはBitget、Hyperliquid Core、Asterのactive crypto linear perpetualを扱う
Perp Universe Explorerと、確認済みの外部参照を使うデイトレランキング。稼働配置は運用記録で確認する。
これは現行実装範囲であり、将来のasset class、Venue、データ源、ranking、
forecast、Chart、保存方式の上限ではない。

製品境界の正本は[`product-boundary.md`](product-boundary.md)。

## 現行実装の機能

- 3 Venueのcatalogを15分周期、L1を60秒fixed-rateで取得する。
- mark、reference price種別、BBO、funding、OI、24時間出来高、quality、freshness、provenanceを
  Venue別に表示する。
- 検索、Venue、coverage、quality filterでinstrumentを絞る。現在の既定sortはbase、次にVenue。
- 条件を満たすgroupでは参考mark中央値を表示する。
- 選択groupのdepth、trades、book walkを表示する。
- 選択Venueのnative時間足をChartに表示し、過去履歴を追加できる。更新時の表示範囲を保持する。
- 指定したJST時刻を基準に、同じVenue・契約の約定騰落率を表示する。
- 固定参照の騰落率・売買代金ランキングと、順位変化・平常比・JST当日高安位置を表示する。
- Past Noteを`venueInstrumentId`単位でローカル保存する。
- Postgresの期限後履歴を照合済みParquetへ保存してbounded retentionする。

現在の3 Venue、更新周期、sort、timeframe、bar数、depth/trade件数、book-walk notional、artifact数、retention等は
実装値であり、将来変更可能である。

## 将来拡張

必要なdata contract、検証、運用設計を伴えば次を追加できる。

- Attention / momentum / direction / LONG・SHORT候補等のrankingとscore
- Stocks、ETF、RWAその他のasset class
- 追加Venue、aggregator、read-only broker/market-data source
- 正規paid market data、credential付きread-only API
- prediction、ML、forecast model
- backtest、feature engineering、bounded historical backfill
- cross-market comparison、正規化可能なfeature集約、dispersion/opportunity ranking
- Decision Memo、Trade Journal、review workflow
- read-only portfolio/account context
- remote access / multi-device

## 既定で含めないもの

自動注文、資金移動、無人executionは現在の既定責務に含めない。これらを導入する場合はsecurity、権限、
kill switch、audit、rollbackを扱う別Decisionを要求する。

これはranking、score、方向評価、prediction、read-only account data、journalを禁止する意味ではない。

## Data integrity

- 取得不能、stale、単位不明を0や前回値へ変換しない。
- source、時刻、単位、identity、quality、provenanceを保持する。
- symbol名だけからaliasやcross-market identityを推測しない。
- rankingやpredictionを保証された利益や確実な約定可能性として表示しない。

## 現行構成

- `apps/market-core`: Python 3.13、CLI `watchdeck-market`
- `apps/ranking-core`: Python 3.13、独立collector・SQLite・loopback API
- `apps/web`: SvelteKit 2 / Svelte 5、現在はlocalhost UI
- `deploy/market-postgres`: 専用Postgres 17 Compose
- `schemas`: 現行Web read model schema
- `config/systemd`: 現行user unit template

現在値は`watchdeck-market status`、artifact、service log、実画面で確認する。
