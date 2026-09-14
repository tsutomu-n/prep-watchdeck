# Decision 0003: Cold snapshotとHot tickerを分離する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** Decision 0011でproduction contractは置換済み。
> 将来のlane構成、ranking、refresh方式等の製品境界はDecision 0012へ委譲する。
> 下記の固定値・責任分離を現行または将来の永久制約として使わない。

## 当時の決定

Dashboardの基準状態をCold snapshot、最新価格表示をHot ticker、詳細履歴をchart payloadへ分離した。

## 当時の理由

400銘柄で全snapshotを1秒更新すると、payload、parse、reactive update、row reorderの負荷と誤操作riskが高かった。
価格だけをHot laneへ分離し、選択、filter、ranking、draftを安定させる目的だった。

## 当時の不変条件

- Hot tickは価格表示以外を変更しない。
- hidden中はpollを停止する。
- sequence gapではfull stateで復旧する。
- Cold refresh後もmemo、ticket、settingsを再読込で失わない。

これらは旧scanner implementationの契約であり、現在のmarket-coreや将来のranking/model/Stocks laneへ自動適用しない。
