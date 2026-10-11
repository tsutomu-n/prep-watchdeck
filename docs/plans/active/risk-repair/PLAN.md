# 残リスク10件の実装と本番反映

timestamp="2026-10-11(日)_19:47 JST"
- 作成: `2026-10-11T19:17:28+09:00`
- 更新: `2026-10-11T19:47:45+09:00`
- 検証: `2026-10-11T19:47:45+09:00`
- 状態: `実装計画`

## Goal と範囲

ユーザーの「実装。本番反映」に従い、再調査R01-R10の修正、隔離検証、commit、同じ50件scopeへの本番反映とreadbackを行う。元workspace4差分、既存設定、map、protected controls、原evidenceを保全する。push・PR・CIは対象外。100件昇格、30日正式開始、本人受入、実24h容量の完了を今回のsource完了に含めない。

## 実行と完了条件

- [x] R01/R07: Unicode exact IDと正常runのbounded freshnessを受入validatorへ反映。欠損・期限超過を拒否。
- [x] R02/R04/R05: 複数day/map/revision入力、範囲外outcome不変、別edition再開と欠日回収、旧reference retentionを整合。
- [x] R06/R03: 範囲指定/chunk読み、固定protocol/一回判定/同入力の中断再開を実評価入口へ接続。
- [x] R08/R09/R10: path隔離、全容量範囲、worker/lock lifetime、実PID/source/HTTP/collector健康による切戻し判定。
- [x] 関連pytest/Ruff/format/Pyrefly、必要schemaとdocs check、cross-package release gateを実行。
- [ ] 今回の対象差分のみcommitし、tracked sourceから新releaseを構築。
- [ ] hash guardを確認して本番を同scopeへ反映し、実PID/source、HTTP、timer、診断とstrict Recoveryを記録。

## 検証とrollback

変更前に再現済み隔離probeと最小回帰で原因を確認し、各担当の所有pathを分ける。現役PG55432と他project5432をtestに使わない。元release6c06046と全設定hashを保存し、新しく追加した設定のみを取り除く切戻しを準備する。互換publicationと機能復帰を別検証し、DB restore・既存data削除を行わない。

## Checkpoint と未解決

初期source: 267b4e9177697e94c925620306b0eba7af9ecc4c。稼働source6c06046、4services active。再調査時のstrict Recoveryは未達。今回のhost証拠は `/home/tn/watchdeck-local-archive/risk-repair-20261011-191728`。長期受入は実時間と実データを必要とし、source testで補わない。

source gate: Market572、Ranking177、Attention111、Web266、E2E169成功/1skip。独立reviewの午夜所有境界とfinalizer group終了の指摘は修正し、回帰で再確認した。本番配置は次のcheckpoint。
