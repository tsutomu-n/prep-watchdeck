# Prep Watchdeck 現行製品境界

- 作成: `2026-09-14T18:18:00+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## 目的

Prep Watchdeckは、裁量トレーダーが市場から注目対象を発見し、分析し、比較し、最終判断を行うための
local-first market intelligence workspaceである。

現在のproduction実装はBitget、Hyperliquid Core、Asterのcrypto linear perpetualを扱うPerp Universe
Explorerである。この実装範囲を、将来のWatchdeck全体の市場・データ源・分析機能の上限として扱わない。

## 製品として許可するもの

次は、必要なdata contract、検証、運用設計を伴う限りWatchdeckへ追加できる。

- Ranking、score、attention、momentum、direction、LONG/SHORT候補、screening
- Stocks、ETF、RWAその他のasset class、追加Venue、aggregator、Discovery source
- read-only API key、credential付きread-only API、正規paid market data
- forecast、ML、TimesFM、Chronosその他の裁量補助model
- backtest、feature engineering、bounded historical backfill
- cross-market comparison、正規化可能なfeature集約、spread/dispersion/opportunity ranking
- 単独instrumentのChart、indicator、ranking、analysis
- 複数symbolの限定capture、任意timeframe、可変bar数、可変depth/trade保持
- 可変notional、確認済みfee、明示的前提を伴うexecution context
- Past Note、Decision Memo、Trade Journal、review workflow
- read-only portfolio/account context、将来のremote accessやmulti-device
- 新しいartifact、API、schema、route、UI surface

未実装であることを禁止と読み替えない。

## 既定で含めないもの

自動注文、資金移動、無人executionは現在の既定責務に含めない。これらを導入する場合はsecurity、権限、
事故範囲、kill switch、audit、rollbackを扱う別Decisionを要求する。

これはranking、score、prediction、LONG/SHORT候補、trade decision record、read-only account dataを禁止する
意味ではない。

## 維持する品質原則

- missing、stale、partial、invalidを0、前回値、推測値で埋めない。
- data quality、freshness、coverage、operational state、selection stateを必要に応じて分離する。
- source、timestamp、unit、finality、identity、provenanceを保持する。
- symbol名だけからalias、multiplier、cross-market identityを推測して同一視しない。
- 不確実または比較不能な値はnull/理由として公開できるようにする。
- schema validation、atomic write、transaction、readback/checksum、fail-closedを適切な境界で使う。
- secretをsource、artifact、log、issue、文書へ残さない。
- production state/DBとtest/shadow、他project資源を隔離する。
- rankingやpredictionを保証された将来収益、必ず成立する注文、確実な裁定として表現しない。
- keyboard、focus、semantic HTML、色以外の状態表現、reduced-motion等のaccessibilityを維持する。

## 現在の実装値の扱い

現在のcode/schema/docsにある次の値は、現行実装を説明する既定値であり永久制約ではない。

- 3 Venue
- 60秒L1 / 15分Catalog / 5秒Web refresh
- Chart `5m / 15m / 1h / 4h / 24h`
- timeframeごと最大500 bars
- active selection 1件
- depth 20段 / selected trades 100件
- `$100 / $500 / $1,000` book walk
- 4 JSON artifact
- 7日+2時間 / 8日のrecent retention
- localhost URLと現在のsystemd / Postgres配置

変更時にはrate limit、capacity、data quality、migration、rollback等をそのtaskで検証する。

## UI / Design

現在のWatchdeckのdark-first、dense、data-firstなvisual identityは有効な既定デザインである。

ただし、gradient、shadow、radius、card、badge、animation、surface hierarchy、layout、Chart表現等を
永久禁止しない。新しいUIが情報密度、可読性、accessibility、状態意味の一貫性を改善する場合は変更できる。

visual preferenceより次を優先する。

1. dataの意味と品質を誤認させない
2. userが重要なmarket contextを短いeye travelで比較できる
3. stateを色だけに依存させない
4. keyboard/mobileを含め操作可能である
5. decorationがmarket signalと混同されない

## 文書解釈

旧P0のscope freeze、3 Venue限定、ranking禁止、Stocks/RWA禁止、paid/private read-only API禁止、ML禁止、
backtest禁止、trade-support identifier禁止、固定Chart/selection/artifact数等は、現行実装の履歴または
当時のscope controlであり、将来機能の永久禁止として使わない。

製品境界の判断ではこの文書とDecision 0012を優先する。個別の現行data contract、operations、validationは
現在動くruntimeを安全に扱うための契約として尊重し、将来設計の上限とは解釈しない。
