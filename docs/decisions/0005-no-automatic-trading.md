# Decision 0005: 自動売買を責任範囲に含めない

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-08-02T22:00:39+09:00`
- 状態: `設計判断`

---

## 決定

ranking、score、risk tag、green/red movement、Past Noteから、自動的なBUY/SELL指示や
注文を生成しない。

## UI上の帰結

- focus colorは選択と操作対象を表す。
- market up/down、warning、data quality、system stateを別色にする。
- 高scoreや上位rankingを推奨表示にしない。
- stale、missing、partial dataを隠さない。
- 内部`NO_TRADE`は`監視除外候補`と表示し、注文禁止や売買指示の意味を追加しない。
- Past Noteは過去の監視contextであり、entry判断やexecution historyとして表示しない。

## 理由

market dataの候補抽出と、資金・executionを伴う売買判断は責任が異なる。
この境界をUI、API、data model、docsで維持する。
