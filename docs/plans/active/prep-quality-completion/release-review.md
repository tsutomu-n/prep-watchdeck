# 配置の確認資料

- 作成: `2026-09-30T23:21:28+09:00`
- 更新: `2026-09-30T23:21:28+09:00`
- 状態: `実装計画`

---

## 承認前の状態

同梱CODEX_TASK.mdと10_RELEASE_RUNBOOK.mdはcommit/push、main統合、production DB、unit操作、deployを
別承認としている。本資料は実行準備であり、承認済みとしない。source fingerprintは
`eb27bfbb43400d8db786eee83ac6de2364428d54a1f359340360dbbbd63d6784`。
[検証記録](validation-summary.md)と[観測証拠](observed-acceptance.json)に結果を記録した。

ローカルreview用source archiveは`/tmp/prep-watchdeck-source-review-20260930/source.tar.gz`。
同directoryのmanifest.jsonに全file/hashを記録する。release directoryへは未配置。
配置候補`/home/tn/releases/prep-watchdeck/quality-eb27bfbb4340`は未作成。

## 現在の対象

read-onlyのsystemctl showで確認した現行working directory:

- Market: `/home/tn/releases/prep-watchdeck/dc2a8d7/apps/market-core`
- Web: `/home/tn/releases/prep-watchdeck/d1c44d5/apps/web`
- Ranking: `/home/tn/releases/prep-watchdeck/d1c44d5`

対象unitは`prep-watchdeck-market.service`、`prep-watchdeck-web.service`、`prep-watchdeck-ranking.service`。
いずれも確認時active/running。MarketのEnvironmentFile pathは
`/home/tn/.config/prep-watchdeck-market/postgres.env`。内容・secretは読取りや記録の対象としていない。

## 初回配置で承認する範囲の案

1. 検証済み対象差分を作業branchへlocal commitする。push/main統合は別。
2. exact sourceを未作成candidateへ配置し、lockfileどおりの依存とWeb buildを用意する。
3. 専用Postgres、user-workspace/notes、unit/configを既存backup手順で保全してreadbackする。
   backup先は承認後に現行設定から確定し、secretをtool出力へ出さない。
4. Market/Web/Rankingを同じsource組へ切り替えるunit変更・daemon-reload・対象3unit restart。
   DB unit、JustPass、他projectのunitは範囲に含めない。
5. `PREP_WATCHDECK_CANDLE_RECOVERY_ENABLED=false`を維持し、現役Markets、optional GET、
   readonly Fixture/Audit、実画面を受入する。自動注文や外部publishは追加しない。

migrations、dedicated Postgres構成、lockfileへの差分はない。追加はoptional JSON schemaと既存collector_runsの
run_kindで、DB migrationは不要。追加の手動Recovery INSERT予定は**なし**。
対象Market serviceの既存collectorによる通常DB書込みは、配置後も継続する。
native 3 Venueの`--apply`やRecovery有効化は契約・期間・最大request数を指定した別承認で行う。
OpenMarketキー未提供のまま認証設定しない。

## 切戻し

Recovery無効を保ち、task終了後にunit/configを旧directoryへ戻して対象unitをrestart。
新sidecarとimmutable Audit/Fixtureを保持し、既存DB行や補充行を自動DELETEしない。
NoteFile v2と旧Webの互換を仮定せず、配置前のuser-workspace/notes backupを別場所でreadbackし、
必要時だけ承認された状態へ復元する。本番での切替・切戻しは未試験。実端末と日本語IMEの本人確認も必要。
