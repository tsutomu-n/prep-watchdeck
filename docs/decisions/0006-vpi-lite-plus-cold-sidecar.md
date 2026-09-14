# Decision 0006: VPI-Lite+をCold snapshotの補助sidecarに限定する

- 作成: `2026-07-19T15:39:27+09:00`
- 更新: `2026-09-14T18:18:00+09:00`
- 状態: `設計判断`

---

> **旧scannerの履歴:** Decision 0011でproduction contractは置換済み。
> score、ranking、model outputをmain rankingへ入れない等の制約を将来機能へ適用しない。
> 現在のproduct boundaryはDecision 0012を正本とする。

## 当時の決定

VPI-Lite+ V0は`watchdeck service`が生成するCold snapshotだけで計算した。
closed 1分足を入力にし、`summary.vpiLitePlus`を正本、存在するrowの`display.vpiLitePlus`を表示用複製とした。

当時はVPI score/stateを既存main ranking、filter、category、attention scoreへ入れず、1 symbolの計算失敗を隔離した。

## 当時の理由

VPIを異常な市場活動を見つける補助情報として導入し、旧scanner判断と更新頻度を変えず、Cold/Hot laneと
単一DuckDB writerを維持するためだった。

## 現在の解釈

- feature/model failureを他のmarket ingestionへ波及させない考え方は維持できる。
- ranking/score/model outputへfeatureを組み込むこと自体は禁止しない。
- closed bar、timeframe、config load、payload公開範囲等は新featureの要件から再設計できる。
- 高scoreを保証された利益や自動注文と同義にしない原則はDecision 0005に従う。
