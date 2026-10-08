"""Deterministic arithmetic and hostile dependence/multiplicity examples."""

import math
import random
from statistics import fmean, stdev
from typing import Literal

import pytest
from helpers import CUTOFF, feature, generation

from prep_watchdeck_attention.evaluation import (
    BASELINE_VERSION,
    DAY,
    _joint_max_t,
    _metrics,
    _outcomes,
    evaluate_candidate_family,
)
from prep_watchdeck_attention.models import (
    MINUTE,
    AttentionComponent,
    AttentionEvaluationReport,
    CandidatePolicy,
    OutcomeRow,
    RawFeatureValue,
    content_digest,
)
from prep_watchdeck_attention.storage import AttentionStore

START = (CUTOFF // DAY + 1) * DAY


class MemoryStore(AttentionStore):
    """In-memory store adapter; the production store itself has separate tests."""

    def __init__(self, policies, generations, outcomes):
        self.registered = tuple(policies)
        self.generations = list(generations)
        self.outcome_rows = tuple(outcomes)
        self.saved = []
        self.frozen_hash = content_digest([p.model_dump() for p in self.registered])

    def policies(self, family_id=None):
        return tuple(p for p in self.registered if family_id is None or p.family_id == family_id)

    def freeze_family(self, policies):
        assert {p.id: p for p in policies} == {p.id: p for p in self.registered}

    def evidence_generations(self):
        return self.generations

    def latest_outcomes(self):
        return self.outcome_rows

    def save_evaluation(self, report):
        self.saved.append(report)


def policies(*, horizon: Literal[15, 60] = 15):
    common = {
        "family_id": "prospective-1",
        "frozen_at": START - MINUTE,
        "minimum_practical_delta": 0.1,
    }
    return [
        CandidatePolicy(
            id="movement",
            signal="movement",
            version="movement-v1",
            horizon_minutes=horizon,
            **common,
        ),
        *[
            CandidatePolicy(
                id=signal,
                signal=signal,
                version=BASELINE_VERSION,
                horizon_minutes=horizon,
                **common,
            )
            for signal in ("reference-abs-return-15m", "reference-abs-return-1h", "turnover-ratio")
        ],
    ]


def make_store(*, days=40, sensitivity=False, edge=True, horizon: Literal[15, 60] = 15):
    records = []
    outcomes = []
    for day in range(days):
        for slot in range(4 if sensitivity else 1):
            cutoff = START + day * DAY + slot * 360 * MINUTE
            features = []
            for index in range(30):
                value = RawFeatureValue(value=index + 1, status="ready", source="test")
                features.append(
                    feature(f"a{index:02}", cutoff).model_copy(
                        update={
                            "reference_return15m": value,
                            "reference_return1h": value,
                            "reference_turnover_ratio15m": value,
                        }
                    )
                )
            inputs, response = generation(features, generation_id=f"g{day}-{slot}", cutoff=cutoff)
            records.append((inputs, tuple(features), response))
            delta = (1 + (0.1 if day % 2 else -0.1)) if edge else 0
            if sensitivity:
                delta += 20 if slot % 2 else -20
            for index, row in enumerate(features):
                # Both signs remain valid nonnegative opportunity returns.
                value = 40 + delta if index < 10 else 40
                outcomes.append(
                    OutcomeRow(
                        generation_id=inputs.generation_id,
                        asset_id=row.asset_id,
                        reference_key=row.reference_key,
                        horizon_minutes=horizon,
                        status="ready",
                        reason=None,
                        cutoff=cutoff + MINUTE,
                        through=cutoff + (horizon + 1) * MINUTE,
                        settled_at=cutoff + (horizon + 1) * MINUTE,
                        max_abs_return=value,
                        close_return=value,
                        time_to_top_decile_move=5,
                        input_fingerprint=f"{day}-{slot}-{index}",
                    )
                )
    return MemoryStore(policies(horizon=horizon), records, outcomes)


def evaluate(store, **overrides):
    kwargs = {
        "policy_ids": ["movement"],
        "baseline_policy_ids": [
            "reference-abs-return-15m",
            "reference-abs-return-1h",
            "turnover-ratio",
        ],
        "k_values": (10, 20),
        "minimum_practical_delta": 0.1,
        "bootstrap_samples": 399,
        "seed": 47,
    }
    kwargs.update(overrides)
    return evaluate_candidate_family(store, **kwargs)


def test_known_retrieval_arithmetic_and_no_future_selection_backfill():
    store = make_store(days=1)
    rows = []
    for index, outcome in enumerate(store.outcome_rows):
        rows.append(outcome.model_copy(update={"max_abs_return": float(30 - index)}))
    metrics = _metrics(store.registered[0], 10, store.generations, _outcomes(rows)).metrics
    assert metrics.recall == 1
    assert metrics.precision == 0.3
    assert metrics.ndcg == 1
    assert metrics.mean_future_max_abs_return == 25.5
    assert metrics.median_lead_time == 5
    assert metrics.coverage == 1
    assert metrics.unscorable_rate == 0
    assert metrics.set_churn is None
    baseline = _metrics(store.registered[1], 10, store.generations, _outcomes(rows)).metrics
    expected_ndcg = sum((i + 1) / math.log2(i + 2) for i in range(10)) / sum(
        (30 - i) / math.log2(i + 2) for i in range(10)
    )
    assert baseline.ndcg == pytest.approx(expected_ndcg)
    assert baseline.precision == baseline.recall == 0
    assert baseline.mean_future_max_abs_return == 5.5
    rows[0] = rows[0].model_copy(
        update={
            "status": "pending",
            "reason": "not_settled",
            "max_abs_return": None,
            "close_return": None,
            "time_to_top_decile_move": None,
        }
    )
    missing = _metrics(store.registered[0], 10, store.generations, _outcomes(rows)).metrics
    assert missing.mean_future_max_abs_return is None
    assert missing.unscorable_rate == 0.1
    assert missing.recall is None


@pytest.mark.parametrize("horizon", [15, 60])
def test_variable_planted_edge_supported_and_power_is_planning_only(horizon):
    report = evaluate(make_store(horizon=horizon))
    assert len(report.evaluations) == 6
    for row in report.evaluations:
        assert row.decision == "supported"
        assert row.adjusted_p_value == 1 / 400
        assert row.block_count == row.effective_days == 40
        assert row.mean_delta == pytest.approx(1 if row.k == 10 else 0.5)
        assert row.planning_only
        assert row.estimated_power is not None
        assert row.mde80 is not None and row.mde80 > 0
    assert AttentionEvaluationReport.model_validate_json(report.model_dump_json()) == report


def test_order_outcome_generation_and_semantic_duplicate_invariance():
    store = make_store()
    original = evaluate(store)
    store.generations.reverse()
    store.outcome_rows = tuple(reversed(store.outcome_rows)) * 2
    store.generations += store.generations[:2]
    duplicate = store.registered[0].model_copy(update={"id": "alias"})
    store.registered += (duplicate,)
    aliased = evaluate(
        store,
        policy_ids=["movement", "alias"],
        k_values=(20, 10),
        baseline_policy_ids=[
            "turnover-ratio",
            "reference-abs-return-1h",
            "reference-abs-return-15m",
        ],
    )
    assert (
        tuple(r for r in aliased.evaluations if r.policy_id == "movement") == original.evaluations
    )
    alias_rows = [
        r.model_copy(update={"policy_id": "movement"})
        for r in aliased.evaluations
        if r.policy_id == "alias"
    ]
    assert tuple(alias_rows) == original.evaluations
    assert aliased.outcome_fingerprint == original.outcome_fingerprint


def test_many_chance_candidates_joint_correction_does_not_support_winner():
    rng = random.Random(163)
    series = {
        str(candidate): [(START + day * DAY, rng.gauss(0, 1)) for day in range(80)]
        for candidate in range(60)
    }
    winner = max(
        series,
        key=lambda key: (
            fmean(v for _, v in series[key]) / (stdev(v for _, v in series[key]) / math.sqrt(80))
        ),
    )
    one = _joint_max_t({winner: series[winner]}, hours=24, samples=999, seed=7)[winner]
    joint = _joint_max_t(series, hours=24, samples=999, seed=7)[winner]
    assert one.p is not None and one.p < 0.05
    assert joint.p is not None and joint.p > 0.05
    assert joint.p >= one.p


def test_day_six_hour_disagreement_is_inconclusive():
    report = evaluate(make_store(sensitivity=True))
    assert all(r.decision == "inconclusive" for r in report.evaluations)
    for row in report.evaluations:
        assert row.adjusted_p_value is not None and row.adjusted_p_value <= 0.05
        assert row.sensitivity_p_value is not None and row.sensitivity_p_value > 0.05


def test_few_days_and_constant_nonzero_edge_cannot_fabricate_support():
    short = evaluate(make_store(days=5))
    assert all(r.decision == "not_estimable" for r in short.evaluations)
    assert all(r.adjusted_p_value is None and r.estimated_power is None for r in short.evaluations)
    store = make_store()
    store.outcome_rows = tuple(
        row.model_copy(
            update={
                "max_abs_return": 41 if int(row.asset_id[1:]) < 10 else 40,
            }
        )
        for row in store.outcome_rows
    )
    constant = evaluate(store)
    assert all(r.decision == "not_estimable" for r in constant.evaluations)
    assert all(r.estimated_power is None for r in constant.evaluations)


def test_coverage_loss_rejects_even_when_observed_edge_is_large():
    store = make_store()
    records = []
    for inputs, features, response in store.generations:
        rows = []
        for index, row in enumerate(response.rows):
            if index >= 15:
                components = dict(row.components)
                components["movement"] = AttentionComponent(
                    policy_version="movement-v1", status="unavailable", reason="missing"
                )
                row = row.model_copy(update={"components": components})
            rows.append(row)
        records.append((inputs, features, response.model_copy(update={"rows": tuple(rows)})))
    store.generations = records
    result = evaluate(store)
    assert all(r.metrics.coverage == 0.5 for r in result.evaluations)
    assert all(r.decision == "rejected_coverage" for r in result.evaluations)


def test_identical_performance_not_supported_and_churn_measured():
    result = evaluate(make_store(edge=False))
    assert all(r.decision == "not_supported" for r in result.evaluations)
    assert all(r.adjusted_p_value == 1 for r in result.evaluations)
    assert all(r.metrics.set_churn == r.metrics.rank_churn == 0 for r in result.evaluations)


def test_high_planned_power_cannot_override_frozen_practical_delta():
    store = make_store()
    store.registered = tuple(
        p.model_copy(update={"minimum_practical_delta": 2}) for p in store.registered
    )
    report = evaluate(store, minimum_practical_delta=2)
    assert all(r.estimated_power == 1 for r in report.evaluations)
    assert all(r.decision == "not_supported" for r in report.evaluations)


def test_freeze_contract_and_prefreeze_rows_excluded():
    store = make_store(days=3)
    with pytest.raises(ValueError, match="entire frozen family"):
        evaluate(store, baseline_policy_ids=["turnover-ratio"])
    with pytest.raises(ValueError, match="practical delta"):
        evaluate(store, minimum_practical_delta=0)
    with pytest.raises(ValueError, match="fixed K"):
        evaluate(store, k_values=(10,))
    store.registered = tuple(
        p.model_copy(update={"frozen_at": START + DAY}) for p in store.registered
    )
    report = evaluate(store)
    assert "prefreeze_generations_excluded:2" in report.reasons
    assert all(row.metrics.generation_count == 1 for row in report.evaluations)


def test_latest_outcome_edition_and_identity_are_enforced():
    store = make_store(days=1)
    first = store.outcome_rows[0]
    corrected = first.model_copy(update={"edition": 2, "max_abs_return": 70})
    assert (
        _outcomes([corrected, first, corrected])[(first.generation_id, first.asset_id, 15)]
        == corrected
    )
    with pytest.raises(ValueError, match="conflicting duplicate"):
        _outcomes([first, first.model_copy(update={"max_abs_return": 99})])
    store.outcome_rows = tuple(
        r.model_copy(update={"reference_key": "wrong"}) for r in store.outcome_rows
    )
    result = evaluate(store)
    assert all(r.decision == "rejected_coverage" for r in result.evaluations)
    assert all(r.metrics.mean_future_max_abs_return is None for r in result.evaluations)


def test_empty_prospective_evidence_is_not_a_candidate_rejection():
    store = make_store(days=0)
    report = evaluate(store)
    assert report.evaluations
    assert all(
        e.decision == "not_estimable" and "no_prospective_evidence" in e.reasons
        for e in report.evaluations
    )


def test_pending_outcomes_do_not_reject_candidate_coverage():
    store = make_store(days=1)
    store.outcome_rows = tuple(
        row.model_copy(
            update={
                "status": "pending",
                "reason": "horizon_pending",
                "max_abs_return": None,
                "close_return": None,
                "time_to_top_decile_move": None,
            }
        )
        for row in store.outcome_rows
    )
    report = evaluate(store)
    assert all(
        e.decision == "not_estimable" and "awaiting_mature_prospective_outcomes" in e.reasons
        for e in report.evaluations
    )
