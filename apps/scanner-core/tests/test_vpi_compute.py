from __future__ import annotations

import math
from dataclasses import replace

import pytest

from prep_watchdeck.config.vpi_config import VpiConfig
from prep_watchdeck.vpi.compute import compute_vpi_lite_plus, normalize_input_bars
from prep_watchdeck.vpi.models import (
    FundingState,
    OpenInterestState,
    VpiDataQuality,
    VpiSourceBar,
    VpiState,
)

START_MS = 1_780_000_000_000


@pytest.fixture
def config() -> VpiConfig:
    return VpiConfig.model_validate(
        {
            "enabled": True,
            "benchmark_symbols": ["BTCUSDT", "ETHUSDT"],
            "target_symbols": ["SOLUSDT"],
            "target_order_notional_usd": 300.0,
            "min_required_1m_bars": 120,
            "stale_after_seconds": 180,
            "fast_half_life_bars": 5.0,
            "slow_half_life_bars": 30.0,
            "reason_pressure_threshold": 1.5,
            "early_activity_score": 35.0,
            "active_move_score": 65.0,
            "thin_turnover_notional_multiple": 20.0,
            "single_bar_concentration_threshold": 0.70,
            "funding_overheated_abs_rate": 0.001,
        }
    )


def source_bar(
    index: int,
    *,
    close: float = 100.0,
    turnover: float = 1_000.0,
    usdt_volume: float | None = None,
    is_closed: bool = True,
    updated_at_ms: int | None = None,
) -> VpiSourceBar:
    return VpiSourceBar(
        ts_ms=START_MS + index * 60_000,
        open=close,
        high=close * 1.001,
        low=close * 0.999,
        close=close,
        usdt_volume=turnover if usdt_volume is None else usdt_volume,
        quote_volume=turnover,
        is_closed=is_closed,
        updated_at_ms=updated_at_ms if updated_at_ms is not None else START_MS + index,
    )


def flat_closed_1m_bars(count: int = 120) -> list[VpiSourceBar]:
    return [source_bar(index) for index in range(count)]


def breakout_with_turnover() -> list[VpiSourceBar]:
    bars = flat_closed_1m_bars(120)
    for index in range(110, 120):
        price = 100.0 * (1.012 ** (index - 109))
        bars[index] = replace(
            source_bar(index, close=price, turnover=12_000.0),
            high=price * 1.01,
            low=price * 0.99,
        )
    return bars


def thin_single_bar_spike() -> list[VpiSourceBar]:
    bars = [source_bar(index, turnover=1.0) for index in range(120)]
    bars[-1] = replace(source_bar(119, close=125.0, turnover=1.0), high=130.0, low=99.0)
    return bars


def generated_at(bars: list[VpiSourceBar], lag_ms: int = 60_000) -> int:
    return bars[-1].ts_ms + lag_ms


def test_flat_series_is_calm_and_finite(config: VpiConfig) -> None:
    bars = flat_closed_1m_bars()

    result = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
    )

    assert result.state is VpiState.CALM
    assert result.score == 0.0
    assert result.reason_codes == ()
    assert result.risk_tag_codes == ()
    assert result.data_quality is VpiDataQuality.OK
    assert result.data_as_of == bars[-1].ts_ms
    assert math.isfinite(result.score)


def test_breakout_is_activity_with_deterministic_reason_order(config: VpiConfig) -> None:
    bars = breakout_with_turnover()

    result = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
    )

    assert result.state is VpiState.ACTIVE_MOVE
    assert result.score == 94.1
    assert result.reason_codes == ("ABS_RETURN_UP", "TURNOVER_UP", "RANGE_UP")
    assert result.risk_tag_codes == ()


def test_thin_single_bar_spike_is_structural_risk(config: VpiConfig) -> None:
    bars = thin_single_bar_spike()

    result = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
    )

    assert result.state is VpiState.SINGLE_BAR_SUSPECT
    assert result.score == 65.0
    assert result.risk_tag_codes[:2] == ("THIN_TURNOVER", "SINGLE_BAR_SUSPECT")
    assert result.diagnostics.single_bar_concentration >= 0.70


def test_insufficient_and_stale_states_take_priority(config: VpiConfig) -> None:
    short = flat_closed_1m_bars(30)
    insufficient = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=short,
        config=config,
        generated_at_ms=generated_at(short),
    )
    stale_bars = flat_closed_1m_bars()
    stale = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=stale_bars,
        config=config,
        generated_at_ms=generated_at(stale_bars, 181_000),
    )

    assert insufficient.state is VpiState.DATA_INSUFFICIENT
    assert insufficient.data_quality is VpiDataQuality.INSUFFICIENT
    assert stale.state is VpiState.DATA_STALE
    assert stale.data_quality is VpiDataQuality.STALE


def test_normalization_excludes_open_invalid_and_non_contiguous_history() -> None:
    bars = flat_closed_1m_bars(5)
    bars.append(source_bar(5, is_closed=False))
    bars.append(replace(source_bar(6), high=math.nan))
    bars.append(source_bar(8))

    normalized = normalize_input_bars(bars)

    assert [bar.ts_ms for bar in normalized] == [source_bar(8).ts_ms]


def test_normalization_deduplicates_by_latest_update_and_falls_back_to_quote_volume() -> None:
    older = source_bar(1, turnover=10.0, updated_at_ms=10)
    newer = replace(
        source_bar(1, turnover=50.0, updated_at_ms=20),
        usdt_volume=None,
        quote_volume=75.0,
    )

    normalized = normalize_input_bars([newer, older, source_bar(0)])

    assert len(normalized) == 2
    assert normalized[-1].quote_turnover == 75.0


def test_open_candle_does_not_change_the_latest_closed_result(config: VpiConfig) -> None:
    bars = breakout_with_turnover()
    arguments = {
        "symbol": "SOLUSDT",
        "config": config,
        "generated_at_ms": generated_at(bars),
    }

    closed_result = compute_vpi_lite_plus(source_bars=bars, **arguments)
    with_open = compute_vpi_lite_plus(
        source_bars=[*bars, source_bar(120, close=500.0, turnover=1_000_000.0, is_closed=False)],
        **arguments,
    )

    assert with_open == closed_result


def test_compute_is_order_independent_and_does_not_mutate_input(config: VpiConfig) -> None:
    bars = breakout_with_turnover()
    original = list(bars)
    arguments = {
        "symbol": "SOLUSDT",
        "config": config,
        "generated_at_ms": generated_at(bars),
    }

    ordered = compute_vpi_lite_plus(source_bars=bars, **arguments)
    reversed_result = compute_vpi_lite_plus(source_bars=list(reversed(bars)), **arguments)

    assert ordered == reversed_result
    assert bars == original


def test_funding_and_open_interest_are_context_only(config: VpiConfig) -> None:
    bars = flat_closed_1m_bars()
    baseline = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
    )
    contextual = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
        funding_rate=-0.001,
        holding_amount=100.0,
    )

    assert baseline.funding_state is FundingState.UNKNOWN
    assert baseline.open_interest_state is OpenInterestState.UNKNOWN
    assert contextual.funding_state is FundingState.OVERHEATED
    assert contextual.open_interest_state is OpenInterestState.AVAILABLE
    assert contextual.score == baseline.score
    assert contextual.risk_tag_codes == ("FUNDING_OVERHEATED",)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_ticker_context_is_unknown(config: VpiConfig, value: float) -> None:
    bars = flat_closed_1m_bars()
    result = compute_vpi_lite_plus(
        symbol="SOLUSDT",
        source_bars=bars,
        config=config,
        generated_at_ms=generated_at(bars),
        funding_rate=value,
        holding_amount=value,
    )

    assert result.funding_state is FundingState.UNKNOWN
    assert result.open_interest_state is OpenInterestState.UNKNOWN
    assert 0.0 <= result.score <= 100.0
