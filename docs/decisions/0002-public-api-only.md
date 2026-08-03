# Decision 0002: Bitget public APIだけを使用する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-07-16T23:06:46+09:00`
- 状態: `設計判断`

---

## 決定

Bitget連携はpublic market REST / WebSocketだけを使用する。

## 対象

- instruments
- ticker
- candle
- funding
- open interest

## 対象外

- API key
- balance
- position
- private account stream
- order create/update/cancel
- automated execution

## 理由

このapplicationの責任は候補発見、context確認、判断記録であり、
account操作とexecutionを含めるとsecurity、権限、事故範囲が大きく変わる。
