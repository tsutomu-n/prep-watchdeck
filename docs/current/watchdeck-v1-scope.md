# Watchdeck v1 P0 完成baseline

- 作成: `2026-08-18T22:00:00+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## この文書の役割

この文書は、Watchdeck v1 P0として完成・運用確認した3 Venue Perp Universe Explorerのbaselineを記録する。
P0完成時にscopeを凍結した事実は履歴として残すが、**P0後の製品拡張を禁止する文書ではない**。

将来の製品境界は[`product-boundary.md`](product-boundary.md)と
[Decision 0012](../decisions/0012-product-evolution-boundary.md)を正本とする。

## P0で完成したもの

P0では、Bitget、Hyperliquid Core、Asterのpublic crypto linear perpetualを継続観測し、値の意味、単位、
時刻、取得元、品質を失わずに保存・表示するlocal-first Perp Universe Explorerを完成させた。

Repository実装の完成と、実hostへinstall / migration / cutoverして日常運用を確認した状態を分けて検証した。
これは今後の変更でも有効な検証原則である。

## P0 runtime baseline

P0時点の主要責務:

- 3 Venue instrument catalogとcapability
- 60秒L1 market state
- 確定または導出確定した1分足
- 精算済みFunding event
- 選択中groupのdepthとtrade
- current Postgres、confirmed Parquet、Web read model
- data quality、freshness、coverage、source provenance
- archive、bounded retention、backup、restore

これらのVenue数、周期、選択数、保存量、artifact数はP0の実装値であり、将来変更できる。

## P0 Data Plane

| Dataset | P0内容 | P0正本 |
| --- | --- | --- |
| `market_state_1m` | mark、reference、BBO、current Funding、OI、24h volume、quality | confirmed Parquet |
| `candle_1m` | OHLC、base/notional volume、trade count、finality | confirmed Parquet |
| `funding_events` | 精算時刻、精算済みrate、確認できるinterval、観測時刻 | confirmed Parquet |
| instrument version | 契約定義、単位、tick/step、capability、SCD2有効期間 | Postgres |

Postgresをcurrent/recent truth、confirmed Parquetを期限後履歴正本、JSON artifactを再生成可能なWeb read modelと
した。将来、新dataset、artifact、storage laneを追加することを妨げない。

## P0 Funding境界

現在のFunding runtimeでは次を維持する。

- currentまたはestimated Funding rateは`market_state_1m`へ保存する。
- 精算済み履歴だけを`funding_events`へ保存する。
- 現行自動catch-upは最大48時間。
- catalog version開始以前のeventを自動採用しない。
- 同一instrument version・同一精算時刻のconflictはfail-closed。
- interval不明時はrate per hourを推測しない。
- source failureをVenue / instrument単位で隔離する。

48時間等の値は現行runtimeの既定値であり永久制約ではない。historical backfillを別laneで追加できる。

## P0 UI / data-quality baseline

P0で確立した次の原則は維持する。

- Data Quality、Freshness、Coverage、Operational state、Selection stateを混同しない。
- 更新失敗時は直前snapshotを現在値と誤認させない。
- stale / unavailableを復活させず、nullを0へ変換しない。
- raw reasonと人間向け説明の両方を確認できる。
- source、unit、timestamp、identity、provenanceを失わない。

一方、ranking、score、方向評価、prediction、Chart構成、UI hierarchy等をP0の表示へ永久固定しない。

## P0 completion evidenceの意味

P0で使用したRepository gate、実host確認、archive readback、backup/restore、reboot確認等は、当時のruntimeが
受入条件を満たした証拠である。将来のfeatureを禁止する根拠にはしない。

将来変更では、その変更に近いfocused testと必要なintegration/runtime validationを新しく定義する。

## P0後に許可される拡張

Decision 0012に従い、P0後はranking、Stocks/ETF/RWA、新Venue、aggregator、paid/read-only API、ML、forecast、
backtest、feature engineering、bounded backfill、journal、read-only portfolio context等を採用できる。

旧Scope Freezeに列挙した項目は、P0完成までscope creepを防ぐための一時制約であり、現在は終了している。

## 利用者価値として維持するもの

- 発見: 今どの市場・銘柄を見るか
- 選別: quality、freshness、liquidity、ranking等から確認対象を絞る
- 反証: 複数featureやVenue差から単純な解釈を疑う
- 検証: 表示値の由来、時刻、単位、不確実性を確認する
- 判断: 最終的なtrade decisionは人間が行う
