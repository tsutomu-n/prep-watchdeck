# Decision 0005: 自動executionを既定責務に含めない

- 作成: `2026-07-16T23:06:46+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

## 決定

Watchdeckは、ranking、score、risk tag、direction、prediction、journal等から自動的に注文や資金移動を
実行することを現在の既定責務に含めない。

ranking、score、LONG/SHORT候補、prediction、decision support、read-only account data、Decision Memo、
Trade Journal自体は許可する。

## UI上の帰結

- rankingやscoreは、人間が確認対象を絞るための分析結果として表示できる。
- LONG/SHORT等の方向評価を表示できるが、保証された将来収益や自動注文と同義にしない。
- data quality、freshness、warning、market movement、model outputを必要に応じて識別できるようにする。
- stale、missing、partial、invalid dataを隠さない。
- prediction、ranking、execution estimateには前提、不確実性、data qualityを必要に応じて併記する。

## Executionを導入する場合

自動注文、資金移動、無人executionを導入する場合は、このDecisionを置換または拡張する別Decisionで少なくとも
次を設計する。

- credential権限とsecret管理
- position/balance整合性
- order idempotency
- rate limitとretry
- kill switch / emergency stop
- max loss / max notional等のhard risk limit
- audit log
- partial fill / reject / disconnect recovery
- testnet / shadow / staged rollout
- rollbackとincident response

## 理由

市場の発見・分析・裁量判断支援と、資金を動かすexecutionでは事故範囲と必要な安全設計が異なる。
分析機能の発展を妨げず、executionだけを明示的な別境界として扱う。
