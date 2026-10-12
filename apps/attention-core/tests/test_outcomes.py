import json

import pytest
from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.models import MINUTE, AttentionEvaluationReport
from prep_watchdeck_attention.outcomes import FixtureBarReader, settle_generation_outcomes
from prep_watchdeck_attention.storage import AttentionStore


def reader(*, gap=False, corrected=False, revision="rev1"):
    bars = [
        dict(
            referenceKey=f"bybit:AUSDT:{revision}",
            end=CUTOFF + i * MINUTE,
            open=100,
            high=105 if corrected and i == 3 else 102,
            low=99,
            close=101,
            quoteTurnover=10,
        )
        for i in range(0, 62)
        if not (gap and i == 5)
    ]
    # The cutoff bar is deliberately extreme: it must never enter the future path.
    bars[0]["high"] = 1000
    bars[1]["high"] = 1000  # Overlaps decisionAt; must be excluded too.
    bars[1]["close"] = 100
    return FixtureBarReader.from_payload(
        {
            "schemaVersion": "attention-outcome-input-v1",
            "mapVersion": "map",
            "bars": bars,
            "native": [],
        }
    )


def test_closed_future_path_gaps_revisions_and_correction(tmp_path):
    f = feature()
    inputs, response = generation((f,))
    store = AttentionStore(tmp_path / "attention")
    try:
        store.save_generation(inputs, (f,), response, evidence=True)
        results = settle_generation_outcomes(
            store, reader(), generation_id="test", now_ms=CUTOFF + 14 * MINUTE
        )
        assert all(
            row.status == "pending" and row.max_abs_return is None
            for row in results
            if row.family == "reference"
        )
        results = settle_generation_outcomes(
            store, reader(), generation_id="test", now_ms=CUTOFF + 61 * MINUTE
        )
        reference = [row for row in results if row.family == "reference"]
        assert len(reference) == 2
        assert all(row.cutoff == CUTOFF + MINUTE for row in reference)
        assert all(
            row.max_abs_return == pytest.approx(2) and row.close_return == pytest.approx(1)
            for row in reference
        )
        assert all(row.time_to_top_decile_move == 110 for row in reference)
        edition = reference[0].edition
        again = settle_generation_outcomes(
            store, reader(), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        assert next(r for r in again if r.family == "reference").edition == edition
        store.save_evaluation(
            AttentionEvaluationReport(
                run_id="evaluation",
                family_id="test",
                policy_hashes={},
                outcome_fingerprint="original",
                created_at=CUTOFF + 61 * MINUTE,
                bootstrap_samples=100,
                seed=1,
                evaluations=(),
            )
        )
        fixed = settle_generation_outcomes(
            store, reader(corrected=True), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        assert next(r for r in fixed if r.family == "reference").edition == edition + 1
        corrected = next(r for r in fixed if r.family == "reference").max_abs_return
        assert corrected is not None and round(corrected, 8) == 5
        assert store.evaluations()[0].stale
        assert json.loads((store.artifacts / "evaluation.json").read_text())["stale"]
        gap = settle_generation_outcomes(
            store, reader(gap=True), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        assert all(
            r.status == "unscorable" and r.max_abs_return is None
            for r in gap
            if r.family == "reference"
        )
        revision = settle_generation_outcomes(
            store, reader(revision="rev2"), generation_id="test", now_ms=CUTOFF + 62 * MINUTE
        )
        assert all(
            r.reason == "reference_revision_changed" for r in revision if r.family == "reference"
        )
    finally:
        store.close()
