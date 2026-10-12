from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from prep_watchdeck_market.bundle_files import BundleError
from prep_watchdeck_market.research.files import load_json
from prep_watchdeck_market.research.journal import ObservationJournal, export_snapshot
from prep_watchdeck_market.research.models import ResearchPayload
from prep_watchdeck_market.research.snapshot import verify_snapshot

from .test_research_journal import native_payload

BASE = datetime(2026, 10, 9, tzinfo=UTC)


def rules(**changes):
    from prep_watchdeck_market.research.trials import TrialRules

    values = {
        "decision_start": BASE,
        "train_end": BASE + timedelta(minutes=10),
        "validation_end": BASE + timedelta(minutes=20),
        "study_end": BASE + timedelta(minutes=35),
        "minimum_price_return": "0.001",
        "minimum_activity_ratio": "1",
        "minimum_oi_return": "0.001",
        "holding_minutes": 1,
        "initial_capital": "1000",
        "trade_notional": "100",
        "fee_rate": "0.001",
        "slippage_rate": "0.001",
        "fee_basis": "declared scenario",
        "slippage_basis": "declared scenario",
        "funding_policy": "explicit_zero_scenario",
        "funding_basis": "zero funding sensitivity only",
        "minimum_independent_episodes": 2,
    }
    return TrialRules.model_validate({**values, **changes})


def snapshot(
    tmp_path: Path,
    *,
    missing_oi: int | None = None,
    change_oi=False,
    future=False,
    funding_rate: str | None = None,
    count: int = 33,
    corrected_last_close: str | None = None,
):
    with ObservationJournal(
        tmp_path / "journal",
        clock_error_seconds=0,
        max_gap_seconds=120,
        clock=lambda: current,
    ) as journal:
        for minute in range(1, count + 1):
            current = BASE + timedelta(minutes=minute + 1, seconds=4)
            data = native_payload()
            data["snapshot_at"] = (current - timedelta(seconds=2)).isoformat()
            data["window_start"] = (BASE + timedelta(minutes=minute)).isoformat()
            data["window_end"] = (BASE + timedelta(minutes=minute + 1)).isoformat()
            candle = data["candles"][0]
            candle.update(
                bucket_at=data["window_start"],
                open_price=str(100 + minute),
                close_price=str(101 + minute),
                high_price=str(120 + minute),
                low_price="99",
                observed_at=(current - timedelta(seconds=3)).isoformat(),
            )
            if future and minute > 25:
                candle["close_price"] = str(119 + minute)
            state = data["states"][0]
            state.update(
                bucket_at=data["window_start"],
                first_observed_at=(BASE + timedelta(minutes=minute, seconds=2)).isoformat(),
                last_observed_at=(BASE + timedelta(minutes=minute, seconds=50)).isoformat(),
                open_interest_raw=str(100 + minute if not change_oi else 200 - minute),
            )
            if funding_rate is not None:
                data["funding"] = [
                    {
                        "venue_instrument_version_id": 1,
                        "funding_at": (BASE + timedelta(minutes=minute, seconds=30)).isoformat(),
                        "funding_rate_raw": funding_rate,
                        "funding_interval_seconds": 60,
                        "observed_at": (current - timedelta(seconds=3)).isoformat(),
                    }
                ]
            if missing_oi == minute:
                state["open_interest_raw"] = None
            journal.record(
                ResearchPayload.model_validate(data),
                read_started_at=current - timedelta(seconds=2),
                read_completed_at=current - timedelta(seconds=1),
                elapsed_seconds=1,
            )
        if corrected_last_close is not None:
            for _ in range(2):
                current += timedelta(minutes=1)
                data["snapshot_at"] = (current - timedelta(seconds=2)).isoformat()
                data["window_end"] = current.replace(second=0, microsecond=0).isoformat()
                data["candles"][0]["close_price"] = corrected_last_close
                data["candles"][0]["observed_at"] = (current - timedelta(seconds=3)).isoformat()
                if funding_rate is not None:
                    data["funding"].append(
                        {
                            "venue_instrument_version_id": 1,
                            "funding_at": (
                                current - timedelta(minutes=1, seconds=4) + timedelta(seconds=30)
                            ).isoformat(),
                            "funding_rate_raw": funding_rate,
                            "funding_interval_seconds": 60,
                            "observed_at": (current - timedelta(seconds=3)).isoformat(),
                        }
                    )
                journal.record(
                    ResearchPayload.model_validate(data),
                    read_started_at=current - timedelta(seconds=2),
                    read_completed_at=current - timedelta(seconds=1),
                    elapsed_seconds=1,
                )
    return export_snapshot(tmp_path / "journal", tmp_path / "snapshot")


def run(tmp_path, snap, rule=None):
    from prep_watchdeck_market.research.evaluation import evaluate_trial
    from prep_watchdeck_market.research.trials import bind_trial, register_trial

    registered = register_trial(
        rules() if rule is None else rule, tmp_path / "registration", clock=lambda: BASE
    )
    trial = bind_trial(registered, snap, tmp_path / "trial")
    output = evaluate_trial(trial, snap, tmp_path / "results")
    return load_json(output / "result.json"), output


def test_freeze_requires_forward_registration_and_finite_explicit_costs(tmp_path):
    from pydantic import ValidationError

    from prep_watchdeck_market.research.trials import register_trial

    with pytest.raises(BundleError, match="research_trial_registered_too_late"):
        register_trial(rules(), tmp_path, clock=lambda: BASE + timedelta(seconds=1))
    for change in ({"fee_rate": "NaN"}, {"initial_capital": "0"}, {"fee_basis": ""}):
        with pytest.raises((ValidationError, BundleError)):
            rules(**change)
    omitted = rules().model_dump()
    omitted.pop("slippage_rate")
    from prep_watchdeck_market.research.trials import TrialRules

    with pytest.raises(ValidationError):
        TrialRules.model_validate(omitted)


def test_a_ignores_oi_and_b_only_filters_shared_episode_schedule(tmp_path):
    rising = snapshot(tmp_path / "up")
    falling = snapshot(tmp_path / "down", change_oi=True)
    first, _ = run(tmp_path / "run-up", rising)
    second, _ = run(tmp_path / "run-down", falling)
    assert [d["signal_a"] for d in first["decisions"]] == [
        d["signal_a"] for d in second["decisions"]
    ]
    assert first["arms"]["A"] == second["arms"]["A"]
    assert first["arms"]["B"]["trade_count"] > 0
    assert second["arms"]["B"]["trade_count"] == 0
    assert first["arms"]["A"] == first["arms"]["B"]
    assert first["cash_control"]["final_equity"] == "1000"
    assert first["evidence_kind"] == "synthetic"
    assert first["cost_classification"] == "funding_zero_sensitivity_scenario"
    assert first["status"] == "ESTIMABLE_DESCRIPTIVE"


def test_missing_inputs_are_common_exclusions_and_purges_are_explicit(tmp_path):
    result, _ = run(tmp_path / "run", snapshot(tmp_path / "data", missing_oi=5))
    missing = [d for d in result["decisions"] if "research_oi_missing" in d["exclusions"]]
    assert missing and all(not d["eligible"] for d in missing)
    assert any("research_split_label_purged" in d["exclusions"] for d in result["decisions"])
    for episode in result["episodes"]:
        boundary = {"train": 10, "validation": 20, "test": 35}[episode["split"]]
        assert datetime.fromisoformat(episode["exit_at"]) < BASE + timedelta(minutes=boundary)


def test_fill_follows_signal_knowledge_and_future_changes_do_not_change_past_signals(tmp_path):
    first, _ = run(tmp_path / "r1", snapshot(tmp_path / "s1"))
    second, _ = run(tmp_path / "r2", snapshot(tmp_path / "s2", future=True))
    before = BASE + timedelta(minutes=25)
    for result in (first, second):
        decisions = {d["decision_id"]: d for d in result["decisions"]}
        for episode in result["episodes"]:
            at = datetime.fromisoformat(decisions[episode["decision_id"]]["available_at"])
            assert datetime.fromisoformat(episode["entry_price_at"]) > at
            assert datetime.fromisoformat(episode["entry_at"]) > at
    assert [
        (d["signal_a"], d["signal_b"], d["price_return"])
        for d in first["decisions"]
        if datetime.fromisoformat(d["available_at"]) < before
    ] == [
        (d["signal_a"], d["signal_b"], d["price_return"])
        for d in second["decisions"]
        if datetime.fromisoformat(d["available_at"]) < before
    ]


def test_unknown_funding_is_not_zero_and_insufficient_cash_is_a_recorded_failure(tmp_path):
    snap = snapshot(tmp_path / "data")
    required = rules(
        funding_policy="require_observed_events",
        funding_interval_seconds=60,
        funding_anchor_at=BASE,
        funding_basis="explicit assumed one minute settlement schedule",
    )
    result, _ = run(tmp_path / "unknown", snap, required)
    assert result["status"] == "NOT_ESTIMABLE"
    assert "research_funding_coverage_unknown" in result["reasons"]
    assert result["arms"]["A"]["trade_count"] == 0
    failed, _ = run(tmp_path / "poor", snap, rules(trade_notional="1001"))
    assert failed["status"] == "FAILED"
    assert "research_insufficient_cash" in failed["reasons"]
    assert Decimal(failed["arms"]["A"]["cash"]) >= 0


def test_ledger_identity_and_artifact_immutability(tmp_path):
    snap = snapshot(tmp_path / "data")
    result, path = run(tmp_path / "run", snap)
    for arm in result["arms"].values():
        entries = [e for e in arm["events"] if e["kind"] == "entry"]
        exits = [e for e in arm["events"] if e["kind"] == "exit"]
        with localcontext() as context:
            context.prec = 50
            expected = Decimal("1000") + sum(
                (Decimal(e["cash_delta"]) for e in arm["events"]), Decimal(0)
            )
            assert abs(expected - Decimal(arm["cash"])) < Decimal("1e-40")
        assert len(entries) == len(exits) == arm["trade_count"]
        assert arm["quantity"] == "0"
        assert arm["final_equity"] == arm["cash"]
    original = (path / "result.json").read_bytes()
    from prep_watchdeck_market.research.evaluation import evaluate_trial

    again = evaluate_trial(Path(result["trial_path"]), snap, tmp_path / "run" / "results")
    assert again != path and (path / "result.json").read_bytes() == original
    assert (again / "result.json").read_bytes() == original
    assert verify_snapshot(snap).replay_valid


def test_observed_funding_charged_once_and_cash_failure_preserves_inventory(tmp_path):
    required = rules(
        funding_policy="require_observed_events",
        funding_interval_seconds=60,
        funding_anchor_at=BASE + timedelta(seconds=30),
        funding_basis="assumed UTC thirty second phase and positive rates paid by longs",
    )
    result, _ = run(tmp_path / "normal", snapshot(tmp_path / "s1", funding_rate="0.001"), required)
    assert result["status"] == "ESTIMABLE_DESCRIPTIVE"
    for arm in result["arms"].values():
        funding = [event for event in arm["events"] if event["kind"] == "funding"]
        assert len({event["at"] for event in funding}) == len(funding)
        assert len(funding) == sum(len(episode["funding"]) for episode in result["episodes"])
        with localcontext() as context:
            context.prec = 50
            assert abs(
                -sum((Decimal(event["cash_delta"]) for event in funding), Decimal(0))
                - Decimal(arm["funding_paid"])
            ) < Decimal("1e-40")
    failure, _ = run(
        tmp_path / "expensive", snapshot(tmp_path / "s2", funding_rate="100"), required
    )
    assert failure["status"] == "FAILED"
    assert "research_funding_insufficient_cash" in failure["reasons"]
    for arm in failure["arms"].values():
        assert Decimal(arm["cash"]) >= 0 and Decimal(arm["quantity"]) > 0
        assert not any(event["kind"] == "exit" for event in arm["events"])
        with localcontext() as context:
            context.prec = 50
            assert Decimal(arm["final_equity"]) == Decimal(arm["cash"]) + (
                Decimal(arm["quantity"]) * Decimal(arm["mark_price"])
            )


def test_declared_schedule_cannot_ignore_observed_extra_settlements(tmp_path):
    required = rules(
        funding_policy="require_observed_events",
        funding_interval_seconds=300,
        funding_anchor_at=BASE + timedelta(seconds=30),
        funding_basis="five minute phase assumption contradicted by observed event cadence",
    )
    result, _ = run(tmp_path / "run", snapshot(tmp_path / "data", funding_rate="0.001"), required)
    assert result["status"] == "NOT_ESTIMABLE"
    assert result["arms"]["A"]["trade_count"] == 0
    assert "research_funding_schedule_mismatch" in result["reasons"]


def test_no_trade_and_small_sample_never_claim_profitability(tmp_path):
    snap = snapshot(tmp_path / "data")
    no_trade, _ = run(tmp_path / "none", snap, rules(minimum_price_return="10"))
    assert no_trade["status"] == "NOT_ESTIMABLE"
    assert "research_no_trades" in no_trade["reasons"]
    small, _ = run(tmp_path / "small", snap, rules(minimum_independent_episodes=100))
    assert small["status"] == "NOT_ESTIMABLE"
    assert small["ab_final_equity_difference"] is None
    assert not small["claims"]["profitability_acceptance_criterion"]


def test_bound_input_substitution_is_a_new_immutable_failed_result(tmp_path):
    from prep_watchdeck_market.research.evaluation import evaluate_trial

    snap = snapshot(tmp_path / "data")
    result, path = run(tmp_path / "run", snap)
    substitute = snapshot(tmp_path / "substitute", change_oi=True)
    failed = evaluate_trial(Path(result["trial_path"]), substitute, tmp_path / "failures")
    assert load_json(failed / "result.json")["reasons"] == ["research_trial_input_mismatch"]
    assert load_json(failed / "result.json")["status"] == "FAILED"
    assert load_json(path / "result.json")["status"] == "ESTIMABLE_DESCRIPTIVE"


def test_result_is_independent_of_callers_decimal_rounding(tmp_path):
    from decimal import ROUND_DOWN, ROUND_UP

    snap = snapshot(tmp_path / "data")
    with localcontext() as context:
        context.rounding = ROUND_DOWN
        down, _ = run(tmp_path / "down", snap)
    with localcontext() as context:
        context.rounding = ROUND_UP
        up, _ = run(tmp_path / "up", snap)
    assert down["arms"] == up["arms"]
    assert down["decisions"] == up["decisions"]


def test_unclosed_position_has_end_mark_without_invented_exit(tmp_path):
    result, _ = run(tmp_path / "run", snapshot(tmp_path / "data", count=14))
    assert result["status"] == "NOT_ESTIMABLE"
    assert "research_exit_unavailable" in result["reasons"]
    assert result["open_episodes"]
    for arm in result["arms"].values():
        assert Decimal(arm["quantity"]) > 0
        assert arm["events"][-1]["kind"] == "entry"
        with localcontext() as context:
            context.prec = 50
            assert Decimal(arm["final_equity"]) == Decimal(arm["cash"]) + (
                Decimal(arm["quantity"]) * Decimal(arm["mark_price"])
            )


def test_split_equity_identity_and_test_only_primary_comparison(tmp_path):
    result, _ = run(tmp_path / "run", snapshot(tmp_path / "data", change_oi=True))
    for arm in result["arms"].values():
        with localcontext() as context:
            context.prec = 50
            prior = Decimal("1000")
            for name in ("train", "validation", "test"):
                split = arm["splits"][name]
                assert Decimal(split["initial_equity"]) == prior
                assert Decimal(split["final_equity"]) - prior == Decimal(split["net_equity_change"])
                prior = Decimal(split["final_equity"])
            assert abs(prior - Decimal(arm["final_equity"])) < Decimal("1e-40")
            assert abs(
                Decimal(result["ab_test_equity_change_difference"])
                - (
                    Decimal(result["arms"]["B"]["splits"]["test"]["net_equity_change"])
                    - Decimal(result["arms"]["A"]["splits"]["test"]["net_equity_change"])
                )
            ) < Decimal("1e-40")
    assert result["primary_comparison"] == "test_net_equity_change"


def test_same_bucket_correction_updates_mark_and_funding_without_new_fill_or_past_signal(tmp_path):
    required = rules(
        funding_policy="require_observed_events",
        funding_interval_seconds=60,
        funding_anchor_at=BASE + timedelta(seconds=30),
        funding_basis="assumed one minute settlement phase",
    )
    baseline, _ = run(
        tmp_path / "baseline", snapshot(tmp_path / "s1", count=14, funding_rate="0.001"), required
    )
    corrected, _ = run(
        tmp_path / "corrected",
        snapshot(tmp_path / "s2", count=14, funding_rate="0.001", corrected_last_close="120"),
        required,
    )
    assert [
        (d["available_at"], d["signal_a"], d["signal_b"], d["price_return"])
        for d in baseline["decisions"]
    ] == [
        (d["available_at"], d["signal_a"], d["signal_b"], d["price_return"])
        for d in corrected["decisions"]
    ]
    for name in ("A", "B"):
        old, new = baseline["arms"][name], corrected["arms"][name]
        assert old["mark_price"] == "115" and new["mark_price"] == "120"
        assert old["quantity"] == new["quantity"]
        for kind in ("entry", "exit"):
            assert [event for event in old["events"] if event["kind"] == kind] == [
                event for event in new["events"] if event["kind"] == kind
            ]
        settled_at = (BASE + timedelta(minutes=16, seconds=30)).isoformat()
        funding = next(event for event in new["events"] if event["at"] == settled_at)
        with localcontext() as context:
            context.prec = 50
            assert Decimal(funding["cash_delta"]) == -Decimal(new["quantity"]) * Decimal(
                "120"
            ) * Decimal("0.001")
        assert Decimal(new["quantity"]) > 0
        assert new["events"][-1]["kind"] == "funding"
    assert corrected["open_episodes"][0]["exit_at"] is None
    assert corrected["open_episodes"][0]["funding"][-1]["reference_price"] == "120"
