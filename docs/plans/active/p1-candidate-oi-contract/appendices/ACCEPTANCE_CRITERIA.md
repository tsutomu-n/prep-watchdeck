# 受入条件一覧

- 作成: `2026-08-08T14:21:08+09:00`
- 更新: `2026-08-09T15:39:47+09:00`
- 検証: `2026-08-09T15:39:47+09:00`
- 状態: `実装計画`

---

## AC-P1-001

- 必須: はい
- 条件: 74h component conditions use three-valued logic and composite is true only when both are true.
- 検証: `parameterized long-horizon unit test`
- AC状態: `not_verified`

## AC-P1-002

- 必須: はい
- 条件: Single-condition matches, insufficient history and zero baseline never produce composite true.
- 検証: `long-horizon unit test`
- AC状態: `not_verified`

## AC-P1-003

- 必須: はい
- 条件: Price and turnover match reasons are independently present in reasonCodes.
- 検証: `DTO/provider unit test`
- AC状態: `not_verified`

## AC-P1-004

- 必須: はい
- 条件: Candidate rankings include only composite true rows while Watchlist rows and noTrade diagnostics remain available.
- 検証: `ranking test and focused E2E`
- AC状態: `not_verified`

## AC-P1-005

- 必須: はい
- 条件: OI samples are idempotently stored in 5-minute buckets and older than 24 hours are pruned.
- 検証: `DuckDB store test`
- AC状態: `not_verified`

## AC-P1-006

- 必須: はい
- 条件: OI compares to the exact 60-minute target bucket and missing reference yields UNKNOWN.
- 検証: `resolver and service snapshot test`
- AC状態: `not_verified`

## AC-P1-007

- 必須: はい
- 条件: UNKNOWN OI receives no positive Attention Score contribution.
- 検証: `priority unit test`
- AC状態: `not_verified`

## AC-P1-008

- 必須: はい
- 条件: Candidate displays active thresholds and selected-symbol OI 60m state without a Watchlist column.
- 検証: `focused E2E`
- AC状態: `not_verified`

## AC-P1-009

- 必須: はい
- 条件: featureVersion and rulesetVersion are 3 while schemaVersion remains unchanged.
- 検証: `snapshot unit test`
- AC状態: `not_verified`

## AC-P1-010

- 必須: はい
- 条件: Existing DB initialization is additive and rollback does not require dropping the new table.
- 検証: `store migration test`
- AC状態: `not_verified`

## AC-P1-011

- 必須: はい
- 条件: Existing monitoring behavior passes the full local verification gate.
- 検証: `bash scripts/verify-local.sh`
- AC状態: `not_verified`

## AC-P1-012

- 必須: はい
- 条件: Current docs, ADR and living plans match final implementation and evidence.
- 検証: `document and plan validation`
- AC状態: `not_verified`

## AC-P1-013

- 必須: はい
- 条件: Stale or invalid current ticker OI is not sampled or compared and produces UNKNOWN.
- 検証: `OI/service snapshot test`
- AC状態: `not_verified`

## AC-RQ-001

- 必須: はい
- 条件: One-command fixture startup renders the principal monitoring workflow and new semantics.
- 検証: `runtime smoke`
- AC状態: `not_verified`

## AC-RQ-002

- 必須: はい
- 条件: Isolated finite live smoke succeeds without modifying production state.
- 検証: `CLI and doctor evidence`
- AC状態: `not_verified`

## AC-RQ-003

- 必須: はい
- 条件: Runtime stores at least one valid OI sample and same-bucket writes are idempotent.
- 検証: `runtime DB evidence`
- AC状態: `not_verified`

## AC-RQ-004

- 必須: はい
- 条件: Controlled restart reuses additive OI history and preserves monitoring state.
- 検証: `restart evidence`
- AC状態: `not_verified`

## AC-RQ-005

- 必須: はい
- 条件: Reconnect, resubscribe and ticker/candle ingest recovery are proven by focused test.
- 検証: `reconnect regression test`
- AC状態: `not_verified`

## AC-RQ-006

- 必須: はい
- 条件: Artifacts prove Candidate/Watchlist/null-history responsibility separation.
- 検証: `fixture or live assertion`
- AC状態: `not_verified`

## AC-RQ-007

- 必須: はい
- 条件: Final full gate and diff audit pass with no unresolved P0/P1.
- 検証: `commands and final audit`
- AC状態: `not_verified`

