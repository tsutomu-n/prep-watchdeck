# Attention Core checkpoint

timestamp="2026-10-09(金)_07:17 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T07:17:08+09:00`
- 状態: `実装計画`

F0–F7 source implementation: **PASS**。Product validation: **PARTIAL**。F8: **PARTIAL**（push・配置・初期入力確認は完了、長期受入は未完了）。
検証済みsource commit: `3ea11242423b9de0856da00c26e12c54a3d24ffc`。branch: `ai/attention-core-20261008-2347`。

## 再開点

source実装・ローカル受入、本番配置と初期の実市場入力受入は完了。残件はcapacity/retention、30日prospective evidence、候補優位性、本人の日常利用受入である。今回の明示承認はAttention/Webの配置と必要なunit操作・push。live DB、Provider追加取得、actual captureは対象外。F9 actual captureは別Decisionを要する。

## 実装と証拠

独立Python app、stable read-only inputs、exact identity/時刻、4成分＋confluence、SQLite証拠、15/60分のoffline将来結果、固定候補群のday-block max-T/6h感度分析、3種のshadow allocation、loopback API、`/attention`、隔離runnerを接続した。現行契約は[architecture](../../../current/architecture.md)、[data contracts](../../../current/data-contracts.md)、[UI](../../../current/ui-workflow.md)、[operations](../../../current/operations.md)、[validation](../../../current/validation.md)。採用判断は[Decision 0015](../../../decisions/0015-attention-core.md)。

- `bash scripts/verify-local.sh`: exit 0。Repo 18、Market 216、Ranking 156、Attention 56、Web unit 221、Desktop/Mobile E2E 136 passed。Ruff/Pyrefly/schema、Web check/build、docsも通過。
- 最終の行ごとの基準時刻表示追加後、Web unit 221、check 0 errors/warnings、build、Attention Desktop/Mobile E2E 2 passed。全体gateを不要に反復していない。
- Linux bubblewrapによる2秒の隔離起動・停止に成功。専用stateだけDBを作り、Marketのselection fixtureのhashとRanking rootを保全。実データの意味・capacityの受入ではない。
- 独立レビューはPASS、未解決指摘なし。判断以前の動きをoutcomeへ混ぜない修正と、empty/pending evidenceを候補棄却にしない修正を直接再現で再確認した。
- CLI help、workflow source parse、local script構文、doc metadata/link、diffを確認。Hosted CIは未実行。

項目別の対応test、実行command、log hash、制約は[acceptance.json](acceptance.json)。一時logの保持を前提にせず、同じsourceとcommandで再実行できる。元資料のtask checkboxは依頼時の手順であり、現在の状態はこの記録と受入台帳を参照する。

## 保持する境界

Outcome cutoffは`ceil(decisionAt / minute)`で、Ranking input cutoffとは別。正確なbaseline closeとその後の15/60本を要求する。old closeの補完はしない。lead timeはdecisionAtから測る。訂正はeditionを増やし旧評価をstale化する。

既定familyは3 baseline＋5 component × 2 horizonの16 policyを初回の実時刻にfreezeする。policyを変える場合は新familyを使う。stats methodはversioned approximationであり、powerはplanning-only。実データ上の有効性・利益・production capacityは未確認。

F0–F7 source受入時点ではMarket/Ranking writer、manual selection、Provider、production stateへの書込み、push / merge / PR / deploy / systemd操作は未実施だった。F8での実行状態は下記を参照する。Attention停止後も既存画面は独立して利用できる。専用stateの削除は不要。

## F8 rollout checkpoint

2026-10-09のuser明示指示により、Attention branchのpushと本番配置を完了した。稼働releaseは`944f91bf810ab9e437ee4639407aea1b8be5c3e0`。WebとAttentionのみを切り替え、Market `5b82a7d`とRanking `d4aa5f9`のprocessは同じPIDで継続している。

- Attention unitはenabled/active。512 MiB、CPU 100%、32 tasks、128 file descriptorsの制限と、Market/Ranking input rootのread-only mountを実物で確認した。
- 実市場入力の初期受入は **PASS WITH ISSUES**。577行、movement/activity 534行、positioning 470行、dislocation 466行、confluence 461行は07:15 JSTの標本値。41件の未対応、4 original versionのreview、3数量倍率未確認、native stale等を理由と欠損のまま保持する。
- 隔離420秒で8世代・5分証拠2世代、本番でも複数世代と再起動後の更新を確認。SQLite/artifact一致、strict schema、finite/null、時刻、4成分が揃った場合だけconfluence、初回証拠より前の16 policy freezeを確認した。
- Browserは1440/390幅で577行、成分切替、BTC検索、元時刻、方向、横overflowなし、JS errorなし、write要求なし。Tailscaleの画面/APIも200。実機での本人受入とは区別する。
- Attention停止時はWeb APIが503/no-store、画面は最終577行と基準時刻を保持して更新停止を表示。元API/画面は200、manual selectionとuser workspaceのhashは不変。Attention復帰も確認した。
- 初期容量はoutcome前約5.1 GiB/日、30日換算約153 GiB。容量保証ではなく、retention/archive・outcome増加・30日prospective evidence・候補優位性・本人の日常利用が残る。

切戻し設定とraw evidenceは`/home/tn/.local/share/prep-watchdeck-attention-rollouts/20261009-071212`。停止対象はAttentionのみ。Webも戻す場合は追加した`zzzz-attention-release.conf`を同directoryへ退避し、daemon-reload後にWebだけを再起動する。専用stateとreleaseは保持する。詳細と検証時刻は[受入台帳](acceptance.json)に記録した。

「GISデータ」が地理空間データを指すかは確認中。この記録は本番配置に必要な実市場入力の受入であり、地理空間GISのimportを完了したものではない。CI、PR、main merge、actual capture、live Market DB変更、credential変更は未実施。
