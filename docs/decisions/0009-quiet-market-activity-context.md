# Decision 0009: Quiet Market activity context

- 作成: `2026-08-10T23:10:43+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** production contractはDecision 0011で置換済み。
> activity featureをranking/category/attentionへ入れない等の制約を将来featureへ適用しない。
> 現在のproduct boundaryはDecision 0012を正本とする。

## 当時の決定

15分量倍率を1時間・4時間windowへ拡張し、`BURST / EXPANDING / SUSTAINED / COOLING / NORMAL / UNKNOWN`の
activity phaseを導出した。当時は1h/4h値を選択銘柄contextだけに使い、Candidate、Raw Sort、category、
attention scoreを変更しなかった。

VPI discovery laneも既存targetの発見補助として限定し、旧Watchlist/selection条件の範囲で表示した。

## 現在の解釈

- activity phase、relative volume、market regime等はranking/score/model featureへ組み込める。
- `UNKNOWN`やdata不足を正常値へ変換しない原則は維持する。
- 表示専用かranking入力かはfeature contractで決める。
- scoreを保証された将来収益や自動注文と同義にしない。
- 当時の15m/1h/4h window、phase分類、top 5等は旧実装値であり永久制約ではない。
