from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.domain.features.long_horizon import MIN_REQUIRED_BARS, compute_74h_features
from prep_watchdeck.domain.features.time_grid import (
    FIVE_MINUTES_MS,
    change_pct_at,
    normalize_5m_grid,
)
from prep_watchdeck.features.open_interest import classify_open_interest_change
from prep_watchdeck.screening.priority import priority_score


def test_5m_grid_does_not_shift_missing_rows(make_bars) -> None:
    bars = make_bars(6)
    missing_ts = bars[3].ts
    bars = [bar for bar in bars if bar.ts != missing_ts]
    grid, quality = normalize_5m_grid(bars)

    assert len(grid) == 6
    assert grid[3] is None
    assert quality.missing_bar_count == 1
    assert quality.coverage_ratio < 1.0
    assert change_pct_at(grid, FIVE_MINUTES_MS) is not None
    assert change_pct_at(grid, FIVE_MINUTES_MS * 2) is None


def test_zero_volume_bar_is_valid_not_missing(make_bars) -> None:
    bars = make_bars(3)
    bars[1] = bars[1].model_copy(update={"quote_vol": Decimal("0")})
    grid, quality = normalize_5m_grid(bars)

    assert len(grid) == 3
    assert quality.missing_bar_count == 0
    assert quality.zero_volume_bar_ratio == 1 / 3


def test_74h_price_and_volume_rules_detect_98h_fixture(make_bars) -> None:
    bars = make_bars(MIN_REQUIRED_BARS, quote_vol=Decimal("1000"))
    boosted = []
    for index, bar in enumerate(bars):
        close = bar.close
        quote_vol = bar.quote_vol
        if index >= len(bars) - 1:
            close = close * Decimal("1.05")
        if index >= len(bars) - 288:
            quote_vol = Decimal("1500")
        boosted.append(bar.model_copy(update={"close": close, "quote_vol": quote_vol}))

    features = compute_74h_features(boosted)

    assert features.price_change_74h_pct is not None
    assert features.price_change_74h_pct >= 4.0
    assert features.volume_change_74h_24h_pct is not None
    assert features.volume_change_74h_24h_pct >= 15.0
    assert features.user_rule_74h_matched is True
    assert features.price_condition_matched is True
    assert features.turnover_condition_matched is True


def test_74h_volume_is_null_with_889_bars(make_bars) -> None:
    features = compute_74h_features(make_bars(889))

    assert features.volume_change_74h_24h_pct is None
    assert features.price_condition_matched is None
    assert features.turnover_condition_matched is None

    assert features.user_rule_74h_matched is None


def test_74h_components_use_strict_and(make_bars) -> None:
    price_only = _long_horizon_bars(make_bars, price_multiplier=Decimal("1.05"))
    volume_only = _long_horizon_bars(make_bars, current_turnover=Decimal("1500"))

    price_features = compute_74h_features(price_only)
    volume_features = compute_74h_features(volume_only)

    assert price_features.price_condition_matched is True
    assert price_features.turnover_condition_matched is False
    assert price_features.user_rule_74h_matched is False
    assert volume_features.price_condition_matched is False
    assert volume_features.turnover_condition_matched is True
    assert volume_features.user_rule_74h_matched is False


def test_74h_zero_or_nonfinite_baseline_is_unknown(make_bars) -> None:
    zero_turnover = compute_74h_features(
        _long_horizon_bars(
            make_bars,
            price_multiplier=Decimal("1.05"),
            historical_turnover=Decimal("0"),
        )
    )
    zero_price = compute_74h_features(
        _long_horizon_bars(
            make_bars,
            price_anchor=Decimal("0"),
            current_turnover=Decimal("1500"),
        )
    )
    nonfinite_price = compute_74h_features(
        _long_horizon_bars(
            make_bars,
            price_anchor=Decimal("NaN"),
            current_turnover=Decimal("1500"),
        )
    )

    assert zero_turnover.price_condition_matched is True
    assert zero_turnover.turnover_condition_matched is None
    assert zero_turnover.user_rule_74h_matched is None
    assert zero_price.price_condition_matched is None
    assert zero_price.turnover_condition_matched is True
    assert zero_price.user_rule_74h_matched is None
    assert nonfinite_price.price_condition_matched is None
    assert nonfinite_price.user_rule_74h_matched is None


def _long_horizon_bars(
    make_bars,
    *,
    price_multiplier: Decimal = Decimal("1"),
    price_anchor: Decimal | None = None,
    current_turnover: Decimal = Decimal("1000"),
    historical_turnover: Decimal = Decimal("1000"),
):
    bars = make_bars(MIN_REQUIRED_BARS, quote_vol=Decimal("1000"))
    historical_end = len(bars) - 74 * 12
    historical_start = historical_end - 24 * 12
    current_start = len(bars) - 24 * 12
    anchor_index = len(bars) - 1 - 74 * 12
    updated = []
    for index, bar in enumerate(bars):
        values = {}
        if historical_start <= index < historical_end:
            values["quote_vol"] = historical_turnover
        if index >= current_start:
            values["quote_vol"] = current_turnover
        if index == anchor_index and price_anchor is not None:
            values["close"] = price_anchor
        if index == len(bars) - 1:
            values["close"] = bars[anchor_index].close * price_multiplier
        updated.append(bar.model_copy(update=values))
    return updated


def test_open_interest_invalid_values_are_unknown_and_unscored() -> None:
    for current, previous in [
        (None, 100.0),
        (100.0, None),
        (0.0, 100.0),
        (-1.0, 100.0),
        (float("nan"), 100.0),
        (float("inf"), 100.0),
        (100.0, 0.0),
        (100.0, float("nan")),
    ]:
        assert classify_open_interest_change(current, previous, 5.0, -5.0) == "UNKNOWN"

    common = {
        "change_15m": 1.0,
        "volume_ratio_15m": 2.0,
        "turnover_1h": 10_000.0,
        "min_turnover_1h": 5_000.0,
        "btc_relative_15m": "BTC_LINKED",
        "data_quality": "OK",
        "risk_tags": [],
    }
    unknown_score = priority_score(open_interest_state="UNKNOWN", **common)
    increasing_score = priority_score(open_interest_state="INCREASING", **common)

    assert increasing_score - unknown_score == 10.0
