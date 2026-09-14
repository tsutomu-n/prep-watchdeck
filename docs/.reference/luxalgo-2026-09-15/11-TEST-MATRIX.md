# 要求IDと受入テスト

- 作成: `2026-09-15T08:37:15+09:00`
- 更新: `2026-09-15T08:37:15+09:00`
- 状態: `実装計画`

---

すべて必須。テスト名を固定するためでなく、ユーザーが確認できる意味を守る。既存試験が満たす要求は再利用し、ID→既存testを記録する。fixtureを読み直しただけの一致試験ではなく、実際の実装の入口/出口を呼ぶ。

| ID | 面 | 期待する結果 |
| --- | --- | --- |
| R01 | scope/identity | 単独instrumentも価格profile対象。異なるquote/Venue/versionを混ぜない |
| R02 | window | 61/16/315本境界、穴、重複、version変更、未確定足、observedAt>asOfを拒否 |
| R03 | numeric | 人工fixtureの0/50/70/100点、逆方向0、NaN/Infinity/負volume拒否 |
| R04 | missing | 必須component欠測でscore/rank=null。不要OI欠測では価格rankを維持 |
| R05 | ranking | 同点1,1,3と安定順。scope取得失敗はrankなし、通常履歴不足とは区別 |
| R06 | time | expiry、future skew、再生成による古い入力の鮮度延長なし |
| S01 | immutability | 同id/同payloadは冪等、同id/異payloadは拒否。訂正で当時snapshot不変 |
| S02 | decision | 202受理≠保存完了。request再送・再起動で重複せずcommit後に成功 |
| S03 | atomic | DB commit後publish前停止から再発行。部分JSONをreaderへ渡さない |
| S04 | archive | readback/hash失敗でDB非削除、成功後archive復元で同digest |
| H01 | forward | asOf切上げ分境界から結果を測る。遅延snapshotの過去windowEndを開始にせず、query asOfより未来の結果を漏らさない |
| H02 | censor | horizon未了・欠足・version変更を失敗0にせず件数とcoverageへ |
| H03 | cohort | baselineと条件群で期間/取得条件一致。inactive historical instrumentを落とさない |
| H04 | guards | n=0,1,9,10,29,30をoverall/baseline/halves/year/recency/groups/exportで確認 |
| H05 | wilson | k/n=8/10と4/10の区間が重なってもstable表示なし。不正整数counts拒否 |
| H06 | bootstrap | 欠測日保持の7日block、seed再現、28日/90%有効境界、依存調整不可理由 |
| H07 | period | calendar midpoint、直近30calendar日、一致事例30件との違いを確認 |
| H08 | drilldown | 全事例pagination/CSV件数が集計一致。formula injectionを無害化 |
| H09 | revision | 同query/dataRevision同結果。結果足訂正で新resultId、旧結果不変 |
| E01 | real-schema | Fedのday精度、nullable speaker、未知type/schema、needsReviewを正しく扱う |
| E02 | import | snapshot bootstrap、delta再読込、停止後catchup、cursor失敗時非前進 |
| E03 | freshness | 7日前manifestでstale=falseでも受信側は期限切れ。静かな日と通信断は別 |
| E04 | security | 未知host/redirect/path traversal/巨大gzip/429/timeoutを制限。secret非漏洩 |
| E05 | terms | Congress sourceはnetwork前に拒否。Fed失敗でnative機能は継続 |
| U01 | api | query不正、サイズ、429、404、410、409、503、no-store、localhost/origin制約 |
| U02 | jobs | 同時1/queue8、取消、再起動、遅着結果、query generation違いを処理 |
| U03 | flow | 発見→理由→Chart→判断保存→読戻し→研究→事例→exportのE2E |
| U04 | accessibility | keyboard/focus/IME/reduced-motion/narrow viewport、色に依存しない欠測 |
| U05 | stale-ui | 古いvalidated snapshotは更新停止表示。現在rank/新着強調へ利用しない |
| O01 | isolation | production/他projectのDB/state/portと一致する試験を拒否 |
| O02 | migration | 空DB/旧DBからmigration、再実行、互換reader/無効化を検証 |
| O03 | capacity | 実universeの時間/RSS/lag/payloadと保存容量、budget超過時の抑制 |
| O04 | real-smoke | native実responseとFed実responseの結果をfixture検証と分離して記録 |
| O05 | restart | 停止・disk full・DB timeout・restoreで既存lane継続と保存記録保全 |

## 試験の層

pure計算はpytest、DB/migration/retentionは隔離Postgres integration、read model/validator/UI stateはWeb unit、ユーザーフローはPlaywright。意味の同じ計算をUIとPythonで別々に実装して互いの値を正解にしない。独立expectedと境界・変形試験を併用する。

## 証拠の必要項目

要求ID、実装path、test path/名前、command、exit code、実行件数、環境/DB隔離、入力が実データか人工か、結果path、未確認。性能はhardware/データ量/測定回数。実市場優位は本受入の成功から推定しない。

同梱 `verify_reference.py` は資料と数値例だけを確認する。これを全34項目の実装試験として記録してはならない。全項目がfixture以外の接続面を含め満たされたとき、実装・隔離検証の完了を判定する。
