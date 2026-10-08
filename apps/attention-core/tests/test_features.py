import pytest
from prep_watchdeck_market.models import Venue
from test_inputs import NOW, bundle, instrument, metric_row, ranked, ranking

from prep_watchdeck_attention.features import (
    build_feature_generation,
    mark_dispersion_bps,
    spread_bps,
)


def test_feature_arithmetic_and_native_zero():
    assert spread_bps(99, 101) == 200
    assert mark_dispersion_bps([99, 101]) == 200
    assert mark_dispersion_bps([99, 100, 101]) == 200
    with pytest.raises(ValueError):
        spread_bps(101, 100)
    reference, rows = build_feature_generation(
        bundle(rows=(metric_row(value=0),)), ranking(), decision_at=NOW
    )
    row = rows[0]
    assert row.oi_change15m_median.value == 0
    assert row.native_return15m_median.value == 0
    assert row.native_return15m_median.observations[1].finality == "confirmed"
    assert row.reference_turnover_ratio15m.value == 2
    assert row.reference_close.value == 100
    assert reference.input_skew_seconds == 180
    assert (
        reference
        == build_feature_generation(
            bundle(rows=(metric_row(value=0),)), ranking(), decision_at=NOW
        )[0]
    )


def test_unknown_multiplier_missing_and_normalized_marks():
    base = ranked().originals[0]
    second = base.model_copy(
        update={"venue": "aster", "instrument_id": "aster:BTC", "multiplier": 1000}
    )
    data = bundle((instrument(mark=100), instrument("aster", mark=100000)))
    _, rows = build_feature_generation(data, ranking((ranked((base, second)),)), decision_at=NOW)
    assert rows[0].mark_dispersion_bps.value == 0
    unknown = second.model_copy(update={"multiplier": None})
    _, rows = build_feature_generation(data, ranking((ranked((base, unknown)),)), decision_at=NOW)
    assert rows[0].mark_dispersion_bps.value is None
    assert rows[0].mark_dispersion_bps.reason is not None
    assert "multiplier" in rows[0].mark_dispersion_bps.reason


@pytest.mark.parametrize("values,expected", [([2], 2), ([2, 6], 4), ([2, 9, 5], 5)])
def test_oi_medians_and_funding(values, expected):
    base = ranked().originals[0]
    all_venues: tuple[Venue, ...] = ("bitget", "aster", "hyperliquid")
    venues = all_venues[: len(values)]
    originals = tuple(
        base.model_copy(update={"venue": v, "instrument_id": f"{v}:BTC"}) for v in venues
    )
    items = tuple(
        instrument(v).model_copy(update={"funding_rate_per_hour": value / 100})
        for v, value in zip(venues, values, strict=True)
    )
    data = bundle(
        items, tuple(metric_row(v, value) for v, value in zip(venues, values, strict=True))
    )
    _, rows = build_feature_generation(data, ranking((ranked(originals),)), decision_at=NOW)
    assert rows[0].oi_change15m_median.value == expected
    assert rows[0].funding_abs_max_per_hour.value == max(values) / 100
    if len(values) > 1:
        assert rows[0].funding_range_per_hour.value == pytest.approx(
            (max(values) - min(values)) / 100
        )
    else:
        assert rows[0].funding_range_per_hour.value is None


def test_stale_l1_excluded_with_observation_and_invalid_bbo():
    from datetime import timedelta

    old = instrument().model_copy(update={"observed_at": NOW - timedelta(seconds=121)})
    _, rows = build_feature_generation(bundle((old,)), ranking(), decision_at=NOW)
    assert rows[0].spread_max_bps.value is None
    assert rows[0].spread_max_bps.observations
    assert rows[0].fresh_native_venue_count == 0
    inverted = instrument().model_copy(update={"best_bid": 101, "best_ask": 100})
    _, rows = build_feature_generation(bundle((inverted,)), ranking(), decision_at=NOW)
    assert rows[0].spread_max_bps.status == "invalid"


def test_future_native_observation_rejected():
    from datetime import timedelta

    future = instrument().model_copy(update={"observed_at": NOW + timedelta(seconds=1)})
    with pytest.raises(ValueError, match="future"):
        build_feature_generation(bundle((future,)), ranking(), decision_at=NOW)
