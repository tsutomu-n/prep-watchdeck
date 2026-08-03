# Decision 0004: SnapshotとChartの世代を一致させる

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-07-16T23:06:46+09:00`
- 状態: `設計判断`

---

## 決定

detail chartはsnapshotとは別fileにするが、`snapshotRunId`で同じpublish世代へ
結び付ける。不一致はfail-closedにする。

## Publish順序

1. 全chart temporary fileを準備する。
2. chart setを置換する。
3. DuckDB snapshot/cacheを更新する。
4. live scanだけ必要なarchiveを更新する。
5. `latest.json`を公開する。
6. rowsから外れたstale chartをcleanupする。

## 理由

snapshotとchartを独立に更新すると、表示中のsymbolと異なる世代のbarsを
正しいchartに見せる危険がある。部分成功を隠すより、明示的に拒否する。
