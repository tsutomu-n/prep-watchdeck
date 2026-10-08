# Attention Core 実装計画

timestamp="2026-10-09(金)_00:50 JST"
- 作成: `2026-10-08T23:47:49+09:00`
- 更新: `2026-10-09T00:50:44+09:00`
- 状態: `実装計画`

F0–F7 source implementation: **PASS**。Product validation: **PARTIAL**。F8は未実行で、承認と実データ受入を待つ。
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
- [ ] F8 capacity / live acceptance: separate authorization and evidence required

## Execution / validation

Implementation stays on this clean dedicated branch. Existing source features are retained.
Required boundary tests are grouped by observable failure; full verify-local runs once after integration.
Hosted CI is not executed. The requested CI configuration is updated as source only.
Source, local runtime, prospective evidence, production and actual capture remain distinct statuses.
Acceptance IDs follow the supplied matrix (the short task-1 list uses conflicting numbers).

## Rollback / excluded operations

Stop the isolated Attention process and remove its Web link to leave existing Core and manual selection intact.
No Provider calls, source-state writes, production DB connection, systemd operations, deploy, push, merge or actual capture.
F8 and the 30-day evidence / candidate superiority checks remain not_run until separately authorized.

## Open / interpretations

- Outcome baseline is the first minute boundary at/after decisionAt; require that exact offline close and all later bars.
- Store UTC millisecond times at Attention boundaries consistently with Ranking; reject future observations.
- Cross-Venue mark comparison requires verified quantity normalization; unknown multiplier never guessed.
- Outcome adapter consumes an explicit offline export/read-only copy, never active Ranking SQLite.
