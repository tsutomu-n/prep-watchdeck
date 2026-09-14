# Decision 0008: Candidate 74h ANDとOI 60分契約

- 作成: `2026-08-09T20:30:00+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** Candidate/74hはDecision 0010で退役し、旧scanner/OI production contract全体は
> Decision 0011のmarket-core置換で現行runtimeから外れた。
> ranking、lookback、bucket、retention、feature version等を将来の永久制約として使わない。
> 現在のproduct boundaryはDecision 0012を正本とする。

## 当時の決定

Candidate rankingでは74時間価格componentと24時間USDT売買代金componentのANDを使い、履歴不足や比較不能を
`null`として未一致`false`と区別した。

当時のOI履歴はBitget `holdingAmount`とsource timestampを基に5分bucketへ保存し、exact 60分lookback、
24時間retention等を採用した。stale/invalid時は`UNKNOWN`とし、attention scoreへ加点しなかった。

## 当時の失敗境界

- storage init failureはstartupを失敗させる。
- cycle単位のOI保存/読込失敗はOIを`UNKNOWN`として隔離し、snapshot発行を継続する。
- unknown/nullを未一致や0へ変換しない。

## 現在の解釈

unknown/nullを推測値へ変換しない、feature failureを隔離する、source timestamp/identityを確認する原則は再利用できる。

一方、74h、60分、5分bucket、24時間retention、Candidate gate、scoreへの組込み可否、version番号は旧実装値であり、
新しいranking/feature engineering/backfillを制約しない。
