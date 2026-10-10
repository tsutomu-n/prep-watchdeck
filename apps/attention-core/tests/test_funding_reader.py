"""Funding expiry never borrows the newer Ticker observation clock."""

from datetime import timedelta

import pytest
from test_inputs import NOW, bundle, instrument, metric_row, ranked, ranking

from prep_watchdeck_attention.discovery import build_discovery_rows
from prep_watchdeck_attention.features import build_feature_generation
from prep_watchdeck_attention.models import RawFeatureValue


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        "expired",
        "settled",
        "legacy",
        "future_source",
        "future_observed",
        "future_source_null",
    ],
)
def test_mexc_funding_has_independent_provenance_and_expiry(invalid):
    observed = NOW - timedelta(seconds=30)
    item = instrument("mexc").model_copy(
        update={
            "funding_source_at": observed - timedelta(seconds=1),
            "funding_observed_at": observed,
            "funding_valid_until": observed + timedelta(seconds=90),
        }
    )
    if invalid == "expired":
        item = item.model_copy(update={"funding_valid_until": NOW})
    elif invalid == "settled":
        item = item.model_copy(update={"next_funding_at": NOW})
    elif invalid == "legacy":
        item = item.model_copy(update={"funding_observed_at": None})
    elif invalid in ("future_source", "future_source_null"):
        item = item.model_copy(update={"funding_source_at": NOW + timedelta(seconds=1)})
    elif invalid == "future_observed":
        item = item.model_copy(update={"funding_observed_at": NOW + timedelta(seconds=1)})
    if invalid == "future_source_null":
        # Published Market failure retains original clocks while all Funding values are null.
        item = item.model_copy(
            update={
                "quality": "partial",
                "funding_rate_raw": None,
                "funding_rate_per_hour": None,
                "funding_interval_seconds": None,
                "next_funding_at": None,
            }
        )
    original = (
        ranked()
        .originals[0]
        .model_copy(update={"venue": "mexc", "instrument_id": item.venue_instrument_id})
    )
    market, ranked_response = (
        bundle((item,), rows=(metric_row("mexc", value=5),)),
        ranking((ranked((original,)),)),
    )
    reference, features = build_feature_generation(market, ranked_response, decision_at=NOW)
    native = build_discovery_rows(market, ranked_response, reference, features)[0].native[0]
    assert features[0].fresh_native_venue_count == 1
    assert features[0].spread_max_bps.value == 200
    assert native.mark_price.value == 100
    assert native.open_interest_base.value == 100
    assert native.oi_change["15m"].value == 5
    assert features[0].oi_change15m_median.value == 5
    assert native.funding_rate_per_hour.observations[0].observed_at == (
        None if invalid in ("legacy", "future_observed") else int(observed.timestamp() * 1000)
    )
    if invalid is None:
        assert native.funding_rate_per_hour.value == 0.0001
        assert features[0].funding_abs_max_per_hour.value == 0.0001
    else:
        assert native.funding_rate_per_hour.value is None
        assert native.funding_rate_raw.value is None
        assert native.funding_interval_seconds is None
        assert features[0].funding_abs_max_per_hour.value is None

    if invalid in ("future_source", "future_observed", "future_source_null"):
        stamp = (
            "funding_source_at"
            if invalid in ("future_source", "future_source_null")
            else "funding_observed_at"
        )
        diagnostic = (
            f"funding_timestamp_future:mexc:BTC@1:{stamp}="
            f"{(NOW + timedelta(seconds=1)).isoformat()}"
        )
        assert diagnostic in features[0].quality_reasons
        assert diagnostic in native.quality_reasons
        assert native.funding_rate_per_hour.reason == "funding_timestamp_future"
        assert native.funding_rate_per_hour.observations[0].value is None
        assert native.funding_rate_raw.observations[0].value is None
        decision_ms = int(NOW.timestamp() * 1000)
        for feature in features[0].__dict__.values():
            if isinstance(feature, RawFeatureValue):
                for observation in feature.observations:
                    assert all(
                        t is None or t <= decision_ms
                        for t in (
                            observation.start_at,
                            observation.end_at,
                            observation.observed_at,
                            observation.source_at,
                        )
                    )
        source = native.funding_rate_per_hour.observations[0].source_at
        assert source == (
            None
            if invalid in ("future_source", "future_source_null")
            else int((observed - timedelta(seconds=1)).timestamp() * 1000)
        )
        # Generic feature invariant remains strict for unrelated future observations.
        feature = features[0].spread_max_bps
        future = feature.observations[0].model_copy(update={"source_at": decision_ms + 1})
        with pytest.raises(ValueError, match="future feature observation"):
            features[0].__class__.model_validate(
                {
                    **features[0].model_dump(),
                    "spread_max_bps": feature.model_copy(update={"observations": (future,)}),
                }
            )
