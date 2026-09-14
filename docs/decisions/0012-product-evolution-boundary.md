# Decision 0012: Watchdeckの製品境界を拡張可能な裁量支援へ更新する

- 作成: `2026-09-14T18:18:00+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

## 決定

`prep-watchdeck`の製品境界を、特定の3 Venue crypto Perp監視だけに固定されたUniverse Explorerから、
裁量トレーダーが市場から注目対象を発見し、分析し、比較し、判断を支援するlocal-first market
intelligence workspaceへ更新する。

現在のPerp runtime、Postgres、Parquet、artifact、selection、Chart、depth/tradeは有効な現行実装である。
ただし、現在の市場、Venue、データ源、ランキング手法、分析モデル、Chart timeframe、bar数、保存期間、
selection数、depth段数、trade件数、book-walk notional、artifact数、UI構成を将来の永久制約として扱わない。

## 許可する拡張

明示的な採用判断、データ契約、検証、rollbackを伴う限り、次を製品境界内で許可する。

- ranking、score、attention、momentum、direction、LONG/SHORT候補などの裁量向け優先順位付け
- Stocks、ETF、RWAその他のasset classを、既存Perp contractへ無理に押し込まず独立surfaceとして追加
- 4 Venue目以降、aggregator、Discovery job、read-only broker/market-data connector
- 正規のpaid market data、credential付きread-only API、API keyを必要とするread-only data source
- forecast、ML、TimesFM、Chronosその他のmodelを含む裁量判断補助
- rankingやscreeningの妥当性を検証するbacktest、feature engineering、bounded historical backfill
- 意味・単位・時刻・identityを確認できるデータの正規化、集約、比較、dispersion/opportunity ranking
- group化されていない単独instrumentのChart、indicator、ranking、analysis
- 複数銘柄の限定capture、将来の選択数・depth段数・trade件数・timeframe・bar数の変更
- 可変notional、確認済みfee計算、明示的な前提を持つexecution context
- Past Noteとは別概念のDecision Memo、Trade Journal、review workflow
- 将来のremote access、multi-device、read-only portfolio context。ただしlocal-firstを既定とする
- 新しいartifact、API、schema、UI surface
- 現在のvisual identityを保ちながら、gradient、shadow、radius、card、animation、badge、layout等を再設計

## 維持する安全原則

製品拡張を許可しても、次はデフォルトの安全原則として維持する。

- 自動注文、資金移動、無人executionをWatchdeckの既定責務にしない。導入する場合は別の明示Decisionが必要。
- stale、missing、partial、invalidを現在値、0、前回値として捏造しない。
- source、時刻、単位、finality、identity、quality、provenanceを失わない。
- alias、contract multiplier、cross-market identity等をsymbol名だけから推測して同一視しない。
- schema validation、atomic write、transaction、readback、checksum、fail-closedを必要な境界で維持する。
- secretをGit、log、artifact、issue、文書へ保存しない。
- production DB/stateとtest/shadow、他projectのDB/stateを隔離する。
- data-derived ranking、score、predictionを、保証された将来収益や確実な約定可能性として表示しない。
- accessibility、keyboard focus、色以外の状態表現、reduced-motionを維持する。

## 現在値と製品契約を分離する

次の値は現行実装の既定値・容量設計であり、永久の製品契約ではない。

- `5m / 15m / 1h / 4h / 24h`
- Chart各timeframe最大500 bars
- active selection 1件
- depth最大20段
- selected trades最大100件
- `$100 / $500 / $1,000` book walk
- 4 JSON artifact
- raw 7日+2時間、recent normalized/selected 8日
- 60秒L1、15分catalog、5秒Web poll、15分selection TTL、5分heartbeat
- Bitget / Hyperliquid Core / Asterの3 Venue
- localhost `127.0.0.1:5173`

これらを変更する場合は、必要なperformance、storage、rate limit、data quality、migration、rollbackを
その変更のtaskで検証する。変更可能であること自体に新しい製品境界Decisionは要求しない。

## 既存Decisionとの関係

- Decision 0001のlocal-first方針は維持する。ただしDuckDB等の当時の実装詳細は現行契約ではない。
- Decision 0002のpublic API onlyは、現行3 Venue Perp runtimeの実装履歴として扱う。read-only paid/
  credential APIを製品全体で禁止する部分はsupersedeする。
- Decision 0005の`rankingやscoreから自動的に注文を生成しない`境界は維持する。ranking、score、方向評価、
  predictionそのものを禁止する解釈はしない。
- Decision 0007のmonitoring-only境界と、退役したtrade-support identifierを永久禁止する部分はsupersedeする。
- Decision 0011は現行Perp runtimeのarchitecture、data semantics、operational baselineとして維持するが、
  3 Venue限定、ranking禁止、新Venue/aggregator禁止、Stocks/RWA禁止、paid/private API禁止、特定の固定値を
  製品全体の永久制約とする部分はsupersedeする。

## AI開発者への解釈

`docs/current/`や旧Decisionに、P0完了時点の禁止、除外、固定値、scope freezeが残っていても、
このDecisionと現行product boundaryに反する場合は将来機能を拒否する根拠にしない。

現在未実装の機能は、`未実装`と`禁止`を区別する。既存code/schemaが現在3 Venue Perpに特化していることは、
そのまま汎用化すべき理由にも、新しいsurfaceを禁止する理由にもならない。新機能は必要に応じて既存coreと
分離し、実測と明示的な契約で導入する。
