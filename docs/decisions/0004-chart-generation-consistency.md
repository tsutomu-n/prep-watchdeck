# Decision 0004: SnapshotとChartの世代を一致させる

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** Decision 0011でproduction contractは置換済み。
> Chart timeframe、bar数、publish topology等の将来product boundaryはDecision 0012へ委譲する。
> 下記のDuckDB/snapshot publish順を現行runtimeや将来Chartの永久制約として使わない。

## 当時の決定

detail chartはsnapshotとは別fileにし、`snapshotRunId`で同じpublish世代へ結び付け、不一致をfail-closedにした。

## 当時のPublish順序

1. 全chart temporary fileを準備する。
2. chart setを置換する。
3. DuckDB snapshot/cacheを更新する。
4. live scanだけ必要なarchiveを更新する。
5. `latest.json`を公開する。
6. rowsから外れたstale chartをcleanupする。

## 当時の理由

snapshotとchartを独立更新すると、表示中symbolと異なる世代のbarsを正しいchartに見せる危険があったため。
部分成功を隠すより、generation mismatchを拒否する方針だった。

世代整合性やfail-closedの考え方は再利用できるが、実装手段とChart構成は現在要件から設計する。
