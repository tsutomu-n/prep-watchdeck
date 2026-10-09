# Research remediation implementation plan

timestamp="2026-10-09(金)_15:08 JST"
- 作成: `2026-10-09T14:28:00+09:00`
- 更新: `2026-10-09T15:08:03+09:00`
- 状態: `実装計画`

**Goal:** 研究入力を観測した版のまま保存し、因果時刻と費用を検査して固定A/Bを比較できる。
**Architecture:** Market package内の独立research CLI/library。既存runtimeとはprocess/stateを分離する。
**Tech Stack:** Python 3.13、uv、Pydantic、Polars、psycopg、Typer、stdlib。
**Spec:** [/home/tn/projects/prep-watchdeck/docs/plans/active/research-remediation/GOAL.md](GOAL.md)。承認済み範囲をそのまま実行し、担当外source変更を避ける。

## Global constraints

- No production writes, deployment, unit actions, CI, push, PR, model/provider reruns or old evidence edits.
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

- [ ] 承認されたrelease/DBにMigration 0005を適用し、sourceを配置してProvider finality/intervalを実受入する。
- [ ] 監視と稼働mapの根拠review・validation・採用後monitorを確認する。現在のmapを推測で書き換えない。
- [ ] 研究rootで新しいrule登録後に将来観測し、24時間captureと複数日/30日evidenceを別段階で確認する。
- [ ] Aster OIはnative symbol・単位・side/multiplier・時刻を確認できる取得契約と実応答が揃うまで除外する。
- [ ] hftbacktest engine受入は完全な連続feedとlatency/queue仮定が揃ってから行う。

production DBへのwrite、unit操作、map稼働採用、deployは明示許可後の実行対象。
既存journal・Phase0・runtime stateは保全し、過去availabilityや未観測値を埋めない。
