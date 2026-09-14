# Decision 0002: Bitget public APIだけを使用する

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **製品境界はsuperseded:** [Decision 0012](0012-product-evolution-boundary.md)により、
> API key、credential付きread-only API、正規paid market dataをWatchdeck全体で禁止する解釈は置換された。
> このDecisionは旧Bitget runtimeおよび現行public Perp sourceの設計履歴として参照する。

## 当時の決定

Bitget連携はpublic market REST / WebSocketだけを使用した。

対象:

- instruments
- ticker
- candle
- funding
- open interest

当時の対象外:

- API key
- balance
- position
- private account stream
- order create/update/cancel
- automated execution

## 現在の解釈

- 現行Bitget Perp adapterがpublic APIだけを使う事実は維持する。
- 将来のread-only market data / broker connectorは、API key、credential、paid planを利用できる。
- credentialのscope、secret handling、terms、rate limit、data semantics、rollbackを導入taskで確認する。
- order/write権限や自動executionはDecision 0005に従い別Decisionを要求する。

## 理由

read-only data取得と資金を動かすexecutionでは事故範囲が異なる。現在は両者を同じ`private/API key禁止`へ
まとめず、権限と作用で境界を分ける。
