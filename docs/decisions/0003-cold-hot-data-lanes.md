# Decision 0003: Cold snapshotとHot tickerを分離する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-07-16T23:06:46+09:00`
- 状態: `設計判断`

---

## 決定

Dashboardの基準状態をCold snapshot、最新価格表示をHot ticker、
詳細履歴をchart payloadへ分離する。

## 理由

400銘柄で全snapshotを1秒更新すると、payload、parse、reactive update、
row reorderの負荷と誤操作riskが高い。価格だけをHot laneへ分離すれば、
選択、filter、ranking、draftを安定させられる。

## 不変条件

- Hot tickは価格表示以外を変更しない。
- hidden中はpollを停止する。
- sequence gapではfull stateで復旧する。
- Cold refresh後もmemo、ticket、settingsを再読込で失わない。
