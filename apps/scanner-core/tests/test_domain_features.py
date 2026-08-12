from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from prep_watchdeck.config.templates import load_template
from prep_watchdeck.domain.features.time_grid import (
    FIVE_MINUTES_MS,
    change_pct_at,
    normalize_5m_grid,
)
from prep_watchdeck.features.activity_phase import classify_activity_phase
from prep_watchdeck.features.open_interest import classify_open_interest_change
from prep_watchdeck.features.volume_ratio import volume_ratio_by_timeframe
from prep_watchdeck.models import ContractInfo, TickerInfo
from prep_watchdeck.screening.pipeline import build_scanner_rows
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


def test_volume_ratio_timeframes_keep_15m_golden_and_add_hour_windows(make_bars) -> None:
    bars = make_bars(383, quote_vol=Decimal("10"))
    bars = [
        bar.model_copy(update={"quote_vol": Decimal("20")}) if index >= len(bars) - 48 else bar
        for index, bar in enumerate(bars)
    ]

    ratios = volume_ratio_by_timeframe(bars, baseline_window_bars=288, floor_usdt=1.0)

    assert ratios == {
        "5m": None,
        "15m": 2.0,
        "1h": 2.0,
        "4h": 2.0,
        "24h": None,
    }


def test_volume_ratio_timeframes_fail_closed_for_short_or_nonfinite_data(make_bars) -> None:
    short = volume_ratio_by_timeframe(
        make_bars(382, quote_vol=Decimal("10")),
        baseline_window_bars=288,
        floor_usdt=1.0,
    )
    nonfinite_bars = make_bars(383, quote_vol=Decimal("10"))
    nonfinite_bars[-1] = nonfinite_bars[-1].model_copy(update={"quote_vol": Decimal("NaN")})
    nonfinite = volume_ratio_by_timeframe(
        nonfinite_bars,
        baseline_window_bars=288,
        floor_usdt=1.0,
    )

    assert short["15m"] == 1.0
    assert short["1h"] == 1.0
    assert short["4h"] is None
    assert nonfinite["15m"] is None
    assert nonfinite["1h"] is None
    assert nonfinite["4h"] is None


@pytest.mark.parametrize(
    ("ratios", "expected"),
    [
        ((0.9, 1.5, 1.0), "COOLING"),
        ((1.0, 1.5, 1.5), "SUSTAINED"),
        ((1.5, 1.5, 1.4), "EXPANDING"),
        ((3.0, 1.4, 1.4), "BURST"),
        ((1.0, 1.0, 1.0), "NORMAL"),
        ((None, 1.5, 1.5), "UNKNOWN"),
        ((float("nan"), 1.5, 1.5), "UNKNOWN"),
        ((1.5, float("inf"), 1.5), "UNKNOWN"),
    ],
)
def test_activity_phase_truth_table(ratios, expected) -> None:
    assert (
        classify_activity_phase(
            ratios[0],
            ratios[1],
            ratios[2],
            min_volume_ratio=1.5,
            strong_volume_ratio=3.0,
        )
        == expected
    )


def test_scanner_pipeline_publishes_activity_phase_without_replacing_volume_ratios(
    make_bars,
) -> None:
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    bars = make_bars(config.candles.min_required_bars, quote_vol=Decimal("1000"))
    bars = [
        bar.model_copy(update={"quote_vol": Decimal("2000")}) if index >= len(bars) - 48 else bar
        for index, bar in enumerate(bars)
    ]
    contract = ContractInfo.model_validate(
        {
            "symbol": "ALTUSDT",
            "productType": "USDT-FUTURES",
            "symbolType": "perpetual",
            "symbolStatus": "normal",
            "minTradeUSDT": "5",
        }
    )
    ticker = TickerInfo.model_validate(
        {"symbol": "ALTUSDT", "lastPr": "1.2", "usdtVolume": "1000000"}
    )

    rows = build_scanner_rows(
        config=config,
        contracts=[contract],
        tickers=[ticker],
        candles_by_symbol={"ALTUSDT": bars},
    )

    assert len(rows) == 1
    assert rows[0].volume_ratio_by_tf["15m"] == 2.0
    assert rows[0].volume_ratio_by_tf["1h"] == 2.0
    assert rows[0].volume_ratio_by_tf["4h"] == 2.0
    assert rows[0].activity_phase == "SUSTAINED"


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
