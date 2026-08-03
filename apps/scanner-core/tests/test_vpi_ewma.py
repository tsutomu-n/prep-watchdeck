from __future__ import annotations

import math

import pytest

from prep_watchdeck.vpi.ewma import ewma


def test_ewma_handles_empty_single_and_constant_sequences() -> None:
    assert ewma([], half_life=5.0) == []
    assert ewma([3.5], half_life=5.0) == [3.5]
    assert ewma([2.0, 2.0, 2.0], half_life=5.0) == [2.0, 2.0, 2.0]


def test_ewma_matches_the_half_life_alpha_and_preserves_input() -> None:
    values = [0.0, 10.0, 10.0]
    original = list(values)
    alpha = 1.0 - math.exp(math.log(0.5) / 2.0)

    result = ewma(values, half_life=2.0)

    assert values == original
    assert result == pytest.approx([0.0, 10.0 * alpha, 10.0 * alpha + 10.0 * alpha * (1 - alpha)])


@pytest.mark.parametrize("half_life", [0.0, -1.0, math.nan, math.inf])
def test_ewma_rejects_invalid_half_life(half_life: float) -> None:
    with pytest.raises(ValueError, match="half_life"):
        ewma([1.0], half_life=half_life)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_ewma_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        ewma([1.0, value], half_life=5.0)
