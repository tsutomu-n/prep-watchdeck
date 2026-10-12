# Research remediation implementation plan

timestamp="2026-10-09(金)_16:16 JST"
- 作成: `2026-10-09T14:28:00+09:00`
- 更新: `2026-10-09T16:16:17+09:00`
- 状態: `実装計画`

**Goal:** 研究入力を観測した版のまま保存し、因果時刻と費用を検査して固定A/Bを比較できる。
**Architecture:** Market package内の独立research CLI/library。既存runtimeとはprocess/stateを分離する。
**Tech Stack:** Python 3.13、uv、Pydantic、Polars、psycopg、Typer、stdlib。
**Spec:** [/home/tn/projects/prep-watchdeck/docs/plans/active/research-remediation/GOAL.md](GOAL.md)。承認済み範囲をそのまま実行し、担当外source変更を避ける。

## Global constraints

- Source phase prohibited production operations. The later 2026-10-09 user request authorizes this
  branch push, production deployment, scoped backup/migration/unit/map actions and initial data capture.
  CI, PR/main merge, credential changes, trading, and old evidence edits remain outside this task.
- Unknown data/costs are never zero-filled. Use exact native identity/version/unit and timezone-aware times.
- New state is isolated; outputs are bounded, immutable, strict-JSON, hash-checked and read back.
- Errors use stable safe codes; never expose DSNs, keys, raw exception text or partial success as qualified.
- Tests cover meaningful adversarial behavior, use isolated temporary state, and stay proportionate.
- Primary owns CLI/docs/shared models/integration and final commit. One independent implementer at a time.

## Review focus

1. Payload published but receipt interrupted: offline qualification must fail, originals remain.
2. Reordered/missing/future/version-mismatched rows: no silent coercion or false PIT claim.
3. Funding before entry, same-time exit, duplicate events: one causal charge, no impossible cash.
4. Current interval/map cannot be applied retroactively; partial source failures remain visible.
5. Invalid paths/JSON/nonfinite values/oversize/lock/clock/DB errors produce bounded safe failures.

## Task 1: Provider semantics and monitor diagnosis

**Files:** Own only relevant `apps/market-core/src/prep_watchdeck_market/sources/hyperliquid*candle*.py`,
`sources/aster.py`, required `models.py`/`candles.py`/`candle_audit.py`/catalog integration,
`scripts/market/check-data-operations.py` and directly related tests. Coordinate shared-file needs first.
**Consumes:** Existing catalog/candle contracts and remediation evidence in original `out/`.
**Produces:** Explicit receipt/finality timestamps and late correction policy; Aster interval provenance;
monitor report identifying map/version/identity mismatches without suppressing legitimate failure.
- [x] Reproduce current Hyperliquid early receipt/late finalize/same-bucket update with focused tests.
- [x] Implement finality timestamps without fabricating old-row timestamps; preserve confirmed vs derived.
- [x] Connect official Aster fundingInfo interval, validate units/missing/changed config; hash provenance.
- [x] Test map missing/removed/version mismatch diagnostics, preserve fail-closed monitoring.
- [x] Run affected pytest/Ruff/Pyrefly and report exact files and limitations; no commit by worker.

## Task 2: Observer and immutable snapshot

**Files:** Create `apps/market-core/src/prep_watchdeck_market/research/` models, reader, journal, snapshot;
focused `apps/market-core/tests/test_research_*.py`. Primary owns these.
**Interfaces:** `ResearchPayload` contains instrument/context/candles/states/funding in one RR snapshot;
`Journal.record(payload, read_started_at, read_completed_at, monotonic_elapsed)` appends an edition;
`verify_snapshot(path, cutoff)` returns checked, causal observations plus explicit qualification reasons.
- [x] Write failing hash/correction/future/clock/interruption/identity tests.
- [x] Implement bounded DB reader and isolated immutable payload/publication receipt journal.
- [x] Export exact bytes to self-contained snapshot and verify temporal context/as-of availability.
- [x] Verify read-only SQL and real reader in dedicated temporary database; no production reads required.

## Task 3: Fixed A/B evaluator

**Files:** `research/evaluation.py`, `research/trials.py`, focused evaluator tests.
**Consumes:** Task 2 verified observations at their recorded availability; never trust caller PIT flags.
**Produces:** immutable trial/result with rule/input/evaluator hashes, exclusions, per-arm equity/events,
cash control and NOT_ESTIMABLE for insufficient independent episodes.
- [x] Test A ignores OI values; A/B share eligibility, entry/exit/size/cost and temporal split/purge.
- [x] Freeze rule and snapshot, explicit positive capital and finite cost assumptions before run.
- [x] Implement long-only fully funded event loop, fill after signal availability, funding once at event,
  end mark-to-market, insufficient cash rejection, deterministic failure/no-trade outputs.
- [x] Future mutation leaves past signals unchanged; test fee/funding/equity identities and costs unknown.

## Task 4: Quality and optional tool preparation

**Files:** `research/quality.py`, `research/tool_inputs.py`, focused tests.
**Consumes:** Native immutable datasets/snapshots with exact IDs, validity and hashes.
**Produces:** gap map, common cohort/count report, original-preserving archive reconciliation/backfill
candidate report, strict funding lineage validation; CCXT capability/response comparison and hft feed gate.
- [x] Validate OHLC, expected timestamps only within valid ranges, raw units and funding conflicts.
- [x] Use existing Polars to scan Parquet with bounded window and compare retained rows by native key.
- [x] Refuse false complete coverage, identity drift, nonfinite numeric values and unknown cost assumptions.
- [x] Make optional tool prerequisites actionable; absence of complete book/trade data stays ineligible.

## Task 5: Integrated CLI, documentation and acceptance

**Files:** `research_cli.py`, `cli.py`, generated research schema(s), current research guide, docs index.
**Consumes:** Tasks 1–4. **Produces:** runnable observation/export/verify/trial/evaluate/quality/tool commands.
- [x] Test CLI error codes for unsafe input, interruption, unavailable DB/dependency and invalid snapshots.
- [x] Update current contract/usage/operations, runtime and statistical acceptance remain separate.
- [x] Run directly affected package tests, Ruff check/format, Pyrefly, schema and document checks.
- [x] Independently review integrated diff, fix important issues and preserve frozen evidence.

## Interface review

| Tasks | Shared boundary | Decision |
| --- | --- | --- |
| 1 / 2 | Native candle/catalog data | Reader keeps DB fields; does not reinterpret historical receipt. |
| 2 / 3 | Verified causal observations | Evaluator calls verifier and carries verification reasons. |
| 2 / 4 | Identity/hash/window | Shared validation helpers owned by primary. |
| 3 / 5 | trial/result interface | CLI freezes trial before evaluation, preserves failed result. |
| 4 / 5 | input/output paths | Same immutable bounded publication helpers. |

All task interfaces agree with the source/runtime separation in GOAL. Future hft adoption and Aster OI
acquisition are conditional evidence gates, not permission to fabricate inputs or start execution.

## Source completion / remaining acceptance

Repository実装とlocal gateは完了。gate・review・元データ保全は
[/home/tn/projects/prep-watchdeck/docs/plans/active/research-remediation/acceptance.json](acceptance.json)、現行usage/contractは
[/home/tn/projects/prep-watchdeck/docs/current/research.md](../../../current/research.md)、採用判断は
[/home/tn/projects/prep-watchdeck/docs/decisions/0016-reader-observed-research.md](../../../decisions/0016-reader-observed-research.md)へ反映した。
このplanは以下の未実施受入だけを再開対象として残す。実装作業を未完了と誤認して再実装しない。

- [x] Source 35de6f2を配置し、検証済みbackup後にMigration 0005を適用。3 Venueの新しい確定時刻とAster 452件のinterval provenanceを実確認。
- [x] Map c0b276f328e1ad423f448bfaを根拠review・validation後に採用。monitorで1,096件一致、version不一致0、operationalFailuresなし。
- [x] Future ruleを登録し、独立rootで1,440 samples・60秒間隔・最大24時間の観測を開始。pilotの3観測はreplay/hash検証済み。
- [ ] 24時間captureの終了と品質を確認し、複数日/30日evidenceを別段階で受け入れる。pilotはcandle/state欠測によりqualified_for_ab=false。
- [ ] Aster OIはnative symbol・単位・side/multiplier・時刻を確認できる取得契約と実応答が揃うまで除外する。
- [ ] hftbacktest engine受入は完全な連続feedとlatency/queue仮定が揃ってから行う。

今回のproduction操作は2026-10-09の明示指示に従って実施済み。稼働状態と再開先はacceptanceに記録する。
既存journal・Phase0・runtime stateは保全し、過去availabilityや未観測値を埋めない。

## Running capture and remaining checks

- Unit: `prep-watchdeck-research-bitget-btc-20261009.service`。one-shotで起動済み、enable/restart loopは使わない。
- Research root: `/home/tn/.local/share/prep-watchdeck-research/20261009-bitget-btc-v1-1550`。
- `capture-config.json`とimmutable registrationがrule/sourceを固定する。fee/slippage各10bps、
  fundingゼロは明示した感度scenarioであり、実料金や実損益の受入ではない。
- 2026-10-09 15:54 JSTに開始。正常なら2026-10-10 15:53 JST頃に1,440回を終了する。
  `ExecStopPost`は新snapshot、quality、trial/result、`daily-outcome-*.json`を残す。
  終了3は不適格理由を確認し、成功へ読み替えない。自動再起動してgapを隠さない。
- 初回pilotは実観測・replay/hash検証済み、candle/state gapによりA/B不適格。
  24時間経過だけで資格や統計的優位を認定しない。
- 状態確認は`systemctl --user status prep-watchdeck-research-bitget-btc-20261009.service`。
  停止が必要な場合は同unitだけをstopし、既存journalを保全する。再開は新研究rootと登録を使う。
- Rollback資料とDB dumpは`/home/tn/.local/share/prep-watchdeck-research-rollouts/20261009-154223`。
  切戻し直前の専用DB backupを追加保全し、新readerを止めて保全してから、準備済みの`rollback-unit-candidates/zzzzz-research-schema5-rollback.conf`を
  Market unitへ追加する。対象は`/home/tn/releases/prep-watchdeck/5b82a7d-schema5-compat`であり、
  未修正5b82a7dを直接起動しない。schema5 health・後着更新・219 testsを隔離DBで確認済み。
  現行35de6f2のmaintenance/monitorを維持し、旧Providerの未観測finalityはNULLとする。
  実際の切戻し後にcatalog/native mapを再照合する。今回この切戻しreleaseは起動していない。
  migration列・原本・旧releaseを維持し、downgradeやrestoreを自動実行しない。

最終reviewで判明した終了判定は修正済み。process終了状態・sample数・品質を分け、OOM/signal・
件数不足・終了情報欠落はPARTIALにする。正常完了と品質欠測を含む6ケースを隔離synthetic入力で確認した。
観測中のunitは再起動せず、将来のExecStopPost helperだけをatomicに差し替えた。rule/evaluator hashは不変。
