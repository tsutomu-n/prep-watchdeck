from typing import cast

import pytest

from prep_watchdeck_ranking.models import MINUTE
from prep_watchdeck_ranking.ranking import (
    DAY,
    Generation,
    Period,
    day_range_position,
    turnover_ratio,
)
from prep_watchdeck_ranking.storage import Store

from .conftest import CUTOFF, candle, mapping, reference, seed


@pytest.mark.parametrize(("minutes", "count"), [(15, 95), (60, 23)])
def test_median_excludes_latest_and_uses_exact_nonoverlapping_windows(
    minutes: int, count: int
) -> None:
    # Past median is 100, latest Q0=200. Both endpoints lie on the T-aligned grid.
    windows = [50.0] * (count // 2) + [100.0] + [150.0] * (count // 2) + [200.0]
    values: list[float | None] = [total / minutes for total in windows for _ in range(minutes)]
    assert len(values) == 1440
    result = turnover_ratio(values, minutes)
    assert result.status == "ready" and result.value == pytest.approx(2)
    # One minute moves across the latest-window boundary, changing Q0 and the old median.
    values[-minutes - 1], values[-minutes] = values[-minutes], values[-minutes - 1]
    assert turnover_ratio(values, minutes).value == pytest.approx((200 - 50 / minutes) / 100)


def test_zero_missing_baseline_and_invalid_values() -> None:
    values: list[float | None] = [0.0 if index >= 1425 else 1.0 for index in range(1440)]
    assert turnover_ratio(values, 15).value == 0
    assert turnover_ratio([0.0] * 1440, 15).status == "no_baseline"
    for index in (0, 1400, 1439):
        missing = values.copy()
        missing[index] = None
        assert turnover_ratio(missing, 15).status == "history_missing"
    for value in (-1.0, float("inf"), float("nan")):
        invalid = values.copy()
        invalid[0] = value
        assert turnover_ratio(invalid, 15).status == "invalid_data"
    assert turnover_ratio([1e308] * 1440, 60).status == "invalid_data"


@pytest.mark.parametrize(("close", "expected"), [(80, 0), (100, 50), (120, 100)])
def test_day_position_uses_ohlc_not_close_extrema(
    store: Store, close: float, expected: float
) -> None:
    seed(store, reference(), start_price=100, end_price=close)
    # All earlier closes are 100, but the first candle of the day has genuine wicks.
    start = CUTOFF - 60 * MINUTE
    first = candle(reference(), start + MINUTE).model_copy(update={"high": 120.0, "low": 80.0})
    store.put([first], CUTOFF)
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    for period in ("15m", "1h", "daily"):
        row = gen.response(cast(Period, period), "00:30", "turnover", 0, CUTOFF).rows[0]
        assert row.day_range_position.status == "ready"
        assert row.day_range_position.value == expected
    assert (
        gen.response("daily", "00:30", "turnover", 0, CUTOFF).rows[0].turnover_ratio.status
        == "unsupported_period"
    )


def test_day_start_flat_missing_and_inconsistent_are_explicit(store: Store) -> None:
    seed(store, reference(), end_price=100)
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    assert (
        gen.response("15m", "00:00", "turnover", 0, CUTOFF).rows[0].day_range_position.status
        == "no_range"
    )
    midnight = CUTOFF - 60 * MINUTE
    assert day_range_position(midnight, []).status == "starting"
    assert day_range_position(midnight + MINUTE, []).status == "history_missing"
    # A complete yet inconsistent input must not be clamped to 100%.
    assert (
        day_range_position(midnight + MINUTE, [(midnight + MINUTE, 130, 5, 120, 80)]).status
        == "invalid_data"
    )
    assert (
        day_range_position(midnight + MINUTE, [(midnight + MINUTE, 100, 5, 80, 120)]).status
        == "invalid_data"
    )
    # Midnight candle belongs to yesterday and must not widen today's range.
    rows = [(midnight, 100.0, 5.0, 1000.0, 1.0), (midnight + MINUTE, 100.0, 5.0, 120.0, 80.0)]
    assert day_range_position(midnight + MINUTE, rows).value == 50


@pytest.mark.parametrize(
    ("missing", "day_status"), [(1440, "ready"), (1000, "ready"), (30, "history_missing")]
)
def test_only_new_indicator_missing_keeps_existing_rank(
    store: Store, missing: int, day_status: str
) -> None:
    seed(store, reference())
    with store.connection:
        store.connection.execute(
            "DELETE FROM minute_bars WHERE end=?", (CUTOFF - missing * MINUTE,)
        )
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    row = gen.response("15m", "00:30", "gainers", 0, CUTOFF).rows[0]
    assert row.rank == 1 and row.state == "ready" and row.quote_turnover == 75
    assert row.turnover_ratio.status == ("ready" if missing == 1440 else "history_missing")
    assert row.day_range_position.status == day_status


def test_quantity_multiplier_does_not_rescale_quote_ratio_or_day_position(store: Store) -> None:
    adopted = mapping("BTC")
    item = adopted.rows[0]
    assert item.reference is not None
    multiplied = item.reference.model_copy(update={"multiplier": 1000})
    adopted = adopted.model_copy(
        update={"rows": (item.model_copy(update={"reference": multiplied}),)}
    )
    seed(store, multiplied)
    gen = Generation(adopted, CUTOFF, CUTOFF + 8000, store)
    row = gen.response("15m", "00:00", "gainers", 0, CUTOFF).rows[0]
    assert row.quote_turnover == 75
    assert row.turnover_ratio.value == 1
    assert row.day_range_position.value == 100


def test_late_ohlc_and_turnover_correction_only_affects_new_generation(store: Store) -> None:
    seed(store, reference())
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store)
    amended = candle(reference(), CUTOFF, 110, 80).model_copy(update={"high": 120})
    store.put([amended], CUTOFF)
    # Uncached condition still uses the generation's own high/low and all 24h windows.
    old = gen.response("15m", "03:12", "turnover", 0, CUTOFF).rows[0]
    assert old.turnover_ratio.value == 1 and old.day_range_position.value == 100
    new = Generation(gen.mapping, CUTOFF, CUTOFF + 9000, store)
    row = new.response("15m", "03:12", "turnover", 0, CUTOFF).rows[0]
    assert row.turnover_ratio.value == 2 and row.day_range_position.value == 50
    assert new.series["asset:BTC"].first == CUTOFF - DAY


def test_unavailable_reference_invalidates_indicators_independently(store: Store) -> None:
    seed(store, reference())
    gen = Generation(mapping("BTC"), CUTOFF, CUTOFF + 8000, store, invalid_keys={reference().key})
    row = gen.response("15m", "00:00", "turnover", 0, CUTOFF).rows[0]
    assert row.turnover_ratio.status == row.day_range_position.status == "reference_unavailable"
