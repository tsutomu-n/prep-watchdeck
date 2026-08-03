from __future__ import annotations

from decimal import Decimal

from prep_watchdeck.domain.features.long_horizon import MIN_REQUIRED_BARS, compute_74h_features
from prep_watchdeck.domain.features.time_grid import (
    FIVE_MINUTES_MS,
    change_pct_at,
    normalize_5m_grid,
)


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


def test_74h_volume_is_null_with_889_bars(make_bars) -> None:
    features = compute_74h_features(make_bars(889))

    assert features.volume_change_74h_24h_pct is None
    assert features.user_rule_74h_matched is None
