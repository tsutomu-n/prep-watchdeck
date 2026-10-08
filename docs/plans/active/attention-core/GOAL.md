# Attention Core 実装計画

timestamp="2026-10-09(金)_07:17 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T07:17:08+09:00`
- 状態: `実装計画`

F0–F7 source implementation: **PASS**。Product validation: **PARTIAL**。F8のpush・本番配置は **PASS**。実市場入力の初期受入は **PASS WITH ISSUES**。「GISデータ」の意味は確認中。
検証済みsource: `3ea11242423b9de0856da00c26e12c54a3d24ffc`。根拠は[受入台帳](acceptance.json)と[再開記録](RESUME.md)。

## Goal / Scope

添付設計・実装計画のF0–F7を、Market/Ranking read-onlyの独立appとして実装する。
基準checkout: `5b82a7df4d9784b442bed068d41d8734737faf27`、branch: `ai/attention-core-20261008-2347`。開始時の未commit差分なし。
正本: [設計](01_PrepWatchdeck_Attention_Core_Design_2026-10-08.md)、[実装手順](02_PrepWatchdeck_Attention_Core_Implementation_Plan_2026-10-08.md)、[受入マトリクス](03_PrepWatchdeck_Attention_Core_Acceptance_Matrix_2026-10-08.md)。

## Checkpoints

- [x] F0 package / strict contracts / state isolation
- [x] F1 stable Market bundle / canonical Ranking input
- [x] F2 exact identity / provenance / raw features
- [x] F3 deterministic components / current API
- [x] F4 SQLite prospective evidence
- [x] F5 outcomes / family evaluation
- [x] F6 Web / schema / accessible UI
- [x] F7 shadow hot-set / isolated runner / source acceptance
- [ ] F8 capacity / live acceptance: deployment and initial input acceptance complete; long-term evidence pending

## Execution / validation

Implementation stays on this clean dedicated branch. Existing source features are retained.
Required boundary tests are grouped by observable failure; full verify-local runs once after integration.
Hosted CI is not executed. The requested CI configuration is updated as source only.
Source, local runtime, prospective evidence, production and actual capture remain distinct statuses.
Acceptance IDs follow the supplied matrix (the short task-1 list uses conflicting numbers).

## Rollback / excluded operations

Stop the isolated Attention process and remove its Web link to leave existing Core and manual selection intact.
No Provider calls, Market/Ranking state writes, production DB connection, main merge or actual capture. Attention/Web deployment and current-branch push are authorized for F8.
F8 deployment and initial input acceptance are complete. The 30-day evidence / candidate superiority checks remain pending actual accumulation and offline outcomes.

## Open / interpretations

- Outcome baseline is the first minute boundary at/after decisionAt; require that exact offline close and all later bars.
- Store UTC millisecond times at Attention boundaries consistently with Ranking; reject future observations.
- Cross-Venue mark comparison requires verified quantity normalization; unknown multiplier never guessed.
- Outcome adapter consumes an explicit offline export/read-only copy, never active Ranking SQLite.

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
