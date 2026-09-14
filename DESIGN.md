# Prep Watchdeck Design Guide

- 作成: `2026-06-27T11:11:19+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 検証: `2026-09-14T18:18:00+09:00`
- 状態: `現行`

---

## 位置付け

この文書はWatchdeckの**現在のvisual defaultsと、維持するUX/accessibility原則**を定義する。

旧版の`Design Constitution`のように、gradient、shadow、radius、card、badge、animation、layout、surface hierarchy、
Chart表現を永久禁止しない。製品や分析surfaceの要件に応じて変更できる。

製品境界は[`docs/current/product-boundary.md`](docs/current/product-boundary.md)と
[`docs/decisions/0012-product-evolution-boundary.md`](docs/decisions/0012-product-evolution-boundary.md)を優先する。

## 現在のvisual identity

現在のWatchdeckは次を既定とする。

- dark-first market terminal
- dense / data-first
- Desktopを主分析surface、Mobileをquick reviewにも使える構成
- themeとfontをlocal-firstで選択可能
- 数値はtabular numericを優先
- market movement、quality、warning、focusをsemantic tokenで区別

実際のruntime color、font、spacing、control、focus、Chart tokenは
`apps/web/src/lib/styles/watchdeck-theme.css`を実装上のsource of truthとする。

現在のtheme、font、radius、spacing、row height、control height等は既定値であり、将来変更可能。

## 維持するUX原則

### Data integrity

- missing、stale、partial、unavailableを0、前回値、正常値に見せない。
- prediction、ranking、score、execution estimateを保証された利益や確実な約定として見せない。
- data quality、freshness、operational warning、market movement等を意味上区別する。
- source、timestamp、unit、identity、provenanceを必要な場所から確認できる。

### Accessibility

- keyboardだけで主要操作へ到達できる。
- focusを視覚的に確認できる。
- 色だけを状態やdirectionの唯一の伝達手段にしない。
- semantic HTML、label、ARIA stateを適切に使う。
- reduced-motionを尊重する。
- tap targetは対象deviceで操作可能な大きさを確保する。
- text/non-text contrastを実用上十分に保つ。

### Information hierarchy

- 主要な発見・ranking・Universe surfaceから、selected detailへ短いeye travelで移動できる。
- status/disclaimerが主データを覆い隠さず、必要な不確実性は近接表示する。
- Desktop densityとMobile readabilityのどちらか一方を無条件に優先しない。
- 長いtable、ranking、Chart、depth、notes等はsurfaceごとに最適な表現を選ぶ。

## 自由に再設計できるもの

以下は旧版では強く制限していたが、現在は設計判断で変更できる。

- gradient / glow / shadow
- border radius
- card / panel / drawer / rail / tabs
- badge familyと用途
- animation / transition / micro-interaction
- surface hierarchy
- page background表現
- sticky / floating UI
- Chart style、overlay、indicator表現
- ranking row、heatmap、matrix、sparkline等のvisualization
- Desktop / Mobileのlayout
- color paletteとtheme数
- font scheme

ただし、装飾がmarket signal、quality、warning、selected stateと誤認されないようにする。

## Motion

continuous animationを一律禁止しない。

許可例:

- ranking更新やselection変更の短いtransition
- loading/progress
- Chart interaction
- state changeを理解しやすくするmotion

避けるもの:

- attentionを常時奪うだけの装飾motion
- reduced-motionを無視する必須animation
- motionだけで状態を伝えるUI
- price movementと無関係な点滅をmarket alertのように見せる表現

## Ranking / Prediction UI

ranking、score、LONG/SHORT候補、forecast等を表示できる。

表示時は必要に応じて次を確認できるようにする。

- score/rankの意味
- component / reason
- timeframe / data-as-of
- data quality
- model/ruleset version
- unavailable / insufficient-data reason

`#1`、高score、緑色等を自動的な注文指示と同義にしない。一方で、方向評価を不自然に隠す必要もない。
裁量判断のための情報として明確に表示する。

## Chart

現在実装の`5m / 15m / 1h / 4h / 24h`、最大500 bars、現在のcandle styleは既定値であり永久制約ではない。

将来、任意timeframe、longer history、indicator、overlay、multi-chart、comparison、annotation、drawing等を追加できる。

finality、gap、missing、version boundary等のdata semanticsを視覚表現の都合で捏造しない。

## Selected market / Execution context

現在の20 depth、100 trades、`$100/$500/$1,000` book walkは現行実装値。
将来、可変depth、可変notional、fee、複数symbol capture、追加execution contextへ拡張できる。

推定値には入力dataの鮮度、対象Venue、fee inclusion、impact assumption、order availabilityの意味を必要に応じて
明示する。

## Notes / Journal

Past Noteは現在の観測annotationとして継続できる。
Decision Memo、Trade Journal、review surfaceを別componentとして追加できる。

visual design上、market observation、decision、execution record、post-trade reviewを区別できるようにする。

## Validation

UI変更では変更範囲に応じて次を組み合わせる。

```bash
cd apps/web
bun test
bun run check
bun run build
```

interaction / route / responsive変更は関連Playwrightを実行する。

固定の1440px/390pxだけを永久のdesign targetにはしないが、Desktopとnarrow viewportの両方で主要flowを検証する。
visual lintがtoolchainに存在する場合は利用するが、旧版の美観ルールを維持するためだけに新しい妥当なdesignを拒否しない。
