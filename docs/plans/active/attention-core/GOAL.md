# Attention Core 実装計画

timestamp="2026-10-09(金)_07:10 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T07:10:30+09:00`
- 状態: `実装計画`

F0–F7 source implementation: **PASS**。Product validation: **PARTIAL**。F8のpush・本番反映は2026-10-09のuser指示で承認済み。「GISデータ」の意味は確認中。
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
- [ ] F8 capacity / live acceptance: authorized, in progress; long-term evidence still pending

## Execution / validation

Implementation stays on this clean dedicated branch. Existing source features are retained.
Required boundary tests are grouped by observable failure; full verify-local runs once after integration.
Hosted CI is not executed. The requested CI configuration is updated as source only.
Source, local runtime, prospective evidence, production and actual capture remain distinct statuses.
Acceptance IDs follow the supplied matrix (the short task-1 list uses conflicting numbers).

## Rollback / excluded operations

Stop the isolated Attention process and remove its Web link to leave existing Core and manual selection intact.
No Provider calls, Market/Ranking state writes, production DB connection, main merge or actual capture. Attention/Web deployment and current-branch push are authorized for F8.
F8 deployment is in progress. The 30-day evidence / candidate superiority checks remain pending actual accumulation and offline outcomes.

## Open / interpretations

- Outcome baseline is the first minute boundary at/after decisionAt; require that exact offline close and all later bars.
- Store UTC millisecond times at Attention boundaries consistently with Ranking; reject future observations.
- Cross-Venue mark comparison requires verified quantity normalization; unknown multiplier never guessed.
- Outcome adapter consumes an explicit offline export/read-only copy, never active Ranking SQLite.

## F8 rollout checkpoint

2026-10-09のuser明示指示で、今回のAttention branchのpushと本番反映を開始した。地理空間のGISか実市場データかの確認は並行中。実データ受入の対象は回答に従う。

1. 現行source・unit・稼働版・healthとrollback設定をread-onlyで確認する。
2. 同じsourceで、専用scratch Attention stateとportから現行Market artifacts / Ranking APIだけを読み、世代・欠測・容量・resource使用を観測する。
3. 受入後にAttention専用unit templateと制限を用意し、tracked sourceだけを新releaseへ配置する。WebのWorkingDirectoryを切り替え、Attentionを専用state/8770で起動する。Market/Rankingの既存writer・manual selection・DBは変更しない。
4. API・Browser・実際の世代更新とcgroup制限、既存process継続、Attention停止/復帰時の独立性を確認し、結果をcommit/pushする。

初期確認: Web/Marketはrelease 5b82a7d、Rankingはd4aa5f9。Rankingは4 original contract versionsのreview_requiredを返す。これを自動承認・補完しない。切戻しは旧Web drop-inの復元と新Attention unitの停止。状態は保持し、削除しない。CI、PR、main merge、actual capture、credential変更は依頼に含めない。30日間の証拠が未蓄積なら短時間の確認で代用しない。

進捗: `194d49c`をoriginの同名branchへpush済み。Linux隔離の実市場入力で毎分更新と577行を確認し、専用unit templateのsystemd構文検証を通過。短時間の実測はoutcome前約5.1 GiB/日で、長期capacity/retention受入は未完了。
