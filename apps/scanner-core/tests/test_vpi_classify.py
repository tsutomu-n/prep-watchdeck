from __future__ import annotations

import math

import pytest

from prep_watchdeck.vpi.classify import VpiClassificationInput, classify_vpi_state
from prep_watchdeck.vpi.models import VpiState


def classification(**overrides: object) -> VpiClassificationInput:
    values: dict[str, object] = {
        "score": 0.0,
        "turnover_pressure": 1.0,
        "thin_turnover": False,
        "single_bar_suspect": False,
        "data_stale": False,
        "data_insufficient": False,
    }
    values.update(overrides)
    return VpiClassificationInput(**values)  # type: ignore[arg-type]


def classify(value: VpiClassificationInput) -> VpiState:
    return classify_vpi_state(
        value,
        early_activity_score=35.0,
        active_move_score=65.0,
        reason_pressure_threshold=1.5,
    )


def test_vpi_state_priority_is_fail_closed() -> None:
    assert (
        classify(classification(data_stale=True, data_insufficient=True, score=100.0))
        is VpiState.DATA_STALE
    )
    assert (
        classify(classification(data_insufficient=True, single_bar_suspect=True, score=100.0))
        is VpiState.DATA_INSUFFICIENT
    )
    assert (
        classify(classification(single_bar_suspect=True, thin_turnover=True, score=70.0))
        is VpiState.SINGLE_BAR_SUSPECT
    )
    assert classify(classification(thin_turnover=True, score=70.0)) is VpiState.THIN_VOLATILITY


def test_vpi_state_distinguishes_active_early_and_calm() -> None:
    assert classify(classification(score=70.0, turnover_pressure=1.6)) is VpiState.ACTIVE_MOVE
    assert classify(classification(score=70.0, turnover_pressure=1.4)) is VpiState.EARLY_ACTIVITY
    assert classify(classification(score=35.0)) is VpiState.EARLY_ACTIVITY
    assert classify(classification(score=34.9)) is VpiState.CALM


@pytest.mark.parametrize("score", [math.nan, math.inf, -1.0, 101.0])
def test_vpi_state_returns_unknown_for_invalid_score(score: float) -> None:
    assert classify(classification(score=score)) is VpiState.UNKNOWN
