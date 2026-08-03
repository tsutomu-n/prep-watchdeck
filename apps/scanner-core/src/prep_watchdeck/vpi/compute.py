from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise

from prep_watchdeck.config.vpi_config import VpiConfig
from prep_watchdeck.vpi.classify import VpiClassificationInput, classify_vpi_state
from prep_watchdeck.vpi.ewma import ewma
from prep_watchdeck.vpi.models import (
    FundingState,
    OpenInterestState,
    VpiDataQuality,
    VpiDiagnostics,
    VpiInputBar,
    VpiLitePlusResult,
    VpiSourceBar,
    VpiState,
)

ONE_MINUTE_MS = 60_000
_PRESSURE_EPSILON = 1e-12
_MAX_PRESSURE = 10.0


def normalize_input_bars(source_bars: Sequence[VpiSourceBar]) -> tuple[VpiInputBar, ...]:
    latest_by_timestamp: dict[int, VpiSourceBar] = {}
    for bar in source_bars:
        if not _is_valid_source_bar(bar):
            continue
        current = latest_by_timestamp.get(bar.ts_ms)
        if current is None or _source_bar_order_key(bar) > _source_bar_order_key(current):
            latest_by_timestamp[bar.ts_ms] = bar

    ordered = [
        VpiInputBar(
            ts_ms=bar.ts_ms,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            quote_turnover=_quote_turnover(bar),
        )
        for bar in sorted(latest_by_timestamp.values(), key=lambda item: item.ts_ms)
    ]
    if not ordered:
        return ()

    continuous_start = len(ordered) - 1
    while (
        continuous_start > 0
        and ordered[continuous_start].ts_ms - ordered[continuous_start - 1].ts_ms == ONE_MINUTE_MS
    ):
        continuous_start -= 1
    return tuple(ordered[continuous_start:])


def compute_vpi_lite_plus(
    *,
    symbol: str,
    source_bars: Sequence[VpiSourceBar],
    config: VpiConfig,
    generated_at_ms: int,
    funding_rate: float | None = None,
    holding_amount: float | None = None,
) -> VpiLitePlusResult:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol must not be empty")
    if generated_at_ms < 0:
        raise ValueError("generated_at_ms must be non-negative")

    bars = normalize_input_bars(source_bars)
    abs_log_returns = [
        abs(math.log(current.close / previous.close)) for previous, current in pairwise(bars)
    ]
    turnovers = [bar.quote_turnover for bar in bars]
    range_values = [math.log(bar.high / bar.low) for bar in bars]

    abs_return_pressure = _pressure(
        abs_log_returns,
        fast_half_life=config.fast_half_life_bars,
        slow_half_life=config.slow_half_life_bars,
    )
    turnover_pressure = _pressure(
        turnovers,
        fast_half_life=config.fast_half_life_bars,
        slow_half_life=config.slow_half_life_bars,
    )
    range_pressure = _pressure(
        range_values,
        fast_half_life=config.fast_half_life_bars,
        slow_half_life=config.slow_half_life_bars,
    )

    score = round(
        _clamp(
            _component_score(abs_return_pressure) * 0.45
            + _component_score(turnover_pressure) * 0.35
            + _component_score(range_pressure) * 0.20,
            0.0,
            100.0,
        ),
        1,
    )
    reason_codes = tuple(
        code
        for code, pressure in (
            ("ABS_RETURN_UP", abs_return_pressure),
            ("TURNOVER_UP", turnover_pressure),
            ("RANGE_UP", range_pressure),
        )
        if pressure >= config.reason_pressure_threshold
    )

    turnover_1h = sum(turnovers[-60:])
    thin_turnover = turnover_1h < (
        config.target_order_notional_usd * config.thin_turnover_notional_multiple
    )
    single_bar_concentration = _single_bar_concentration(abs_log_returns[-15:])
    single_bar_suspect = single_bar_concentration >= config.single_bar_concentration_threshold
    funding_state = _funding_state(funding_rate, config.funding_overheated_abs_rate)
    open_interest_state = _open_interest_state(holding_amount)

    risk_tag_codes: list[str] = []
    if thin_turnover:
        risk_tag_codes.append("THIN_TURNOVER")
    if single_bar_suspect:
        risk_tag_codes.append("SINGLE_BAR_SUSPECT")
    if funding_state is FundingState.OVERHEATED:
        risk_tag_codes.append("FUNDING_OVERHEATED")

    data_as_of = bars[-1].ts_ms if bars else None
    data_stale = data_as_of is not None and max(0, generated_at_ms - data_as_of) > (
        config.stale_after_seconds * 1_000
    )
    data_insufficient = len(bars) < config.min_required_1m_bars
    state = classify_vpi_state(
        VpiClassificationInput(
            score=score,
            turnover_pressure=turnover_pressure,
            thin_turnover=thin_turnover,
            single_bar_suspect=single_bar_suspect,
            data_stale=data_stale,
            data_insufficient=data_insufficient,
        ),
        early_activity_score=config.early_activity_score,
        active_move_score=config.active_move_score,
        reason_pressure_threshold=config.reason_pressure_threshold,
    )
    data_quality = _data_quality(state)

    return VpiLitePlusResult(
        symbol=normalized_symbol,
        state=state,
        score=score,
        reason_codes=reason_codes,
        risk_tag_codes=tuple(risk_tag_codes),
        funding_state=funding_state,
        open_interest_state=open_interest_state,
        data_quality=data_quality,
        data_as_of=data_as_of,
        diagnostics=VpiDiagnostics(
            abs_return_pressure=abs_return_pressure,
            turnover_pressure=turnover_pressure,
            range_pressure=range_pressure,
            used_bar_count=len(bars),
            turnover_1h=turnover_1h,
            single_bar_concentration=single_bar_concentration,
        ),
    )


def _is_valid_source_bar(bar: VpiSourceBar) -> bool:
    prices = (bar.open, bar.high, bar.low, bar.close)
    turnover = _quote_turnover(bar)
    return (
        bar.is_closed
        and bar.ts_ms >= 0
        and all(math.isfinite(value) and value > 0 for value in prices)
        and bar.high >= bar.low
        and math.isfinite(turnover)
        and turnover >= 0
    )


def _quote_turnover(bar: VpiSourceBar) -> float:
    if bar.usdt_volume is not None:
        return bar.usdt_volume
    if bar.quote_volume is not None:
        return bar.quote_volume
    return math.nan


def _source_bar_order_key(bar: VpiSourceBar) -> tuple[float, ...]:
    return (
        float(bar.updated_at_ms),
        bar.open,
        bar.high,
        bar.low,
        bar.close,
        _quote_turnover(bar),
    )


def _pressure(values: Sequence[float], *, fast_half_life: float, slow_half_life: float) -> float:
    if not values:
        return 1.0
    fast = ewma(values, half_life=fast_half_life)[-1]
    slow = ewma(values, half_life=slow_half_life)[-1]
    if abs(fast) <= _PRESSURE_EPSILON and abs(slow) <= _PRESSURE_EPSILON:
        return 1.0
    return _clamp(fast / max(slow, _PRESSURE_EPSILON), 0.0, _MAX_PRESSURE)


def _component_score(pressure: float) -> float:
    return _clamp((pressure - 1.0) / 2.0, 0.0, 1.0) * 100.0


def _single_bar_concentration(abs_log_returns: Sequence[float]) -> float:
    total = sum(abs_log_returns)
    if total <= _PRESSURE_EPSILON:
        return 0.0
    return _clamp(max(abs_log_returns) / total, 0.0, 1.0)


def _funding_state(value: float | None, overheated_abs_rate: float) -> FundingState:
    if value is None or not math.isfinite(value):
        return FundingState.UNKNOWN
    if abs(value) >= overheated_abs_rate:
        return FundingState.OVERHEATED
    return FundingState.NORMAL


def _open_interest_state(value: float | None) -> OpenInterestState:
    if value is not None and math.isfinite(value) and value > 0:
        return OpenInterestState.AVAILABLE
    return OpenInterestState.UNKNOWN


def _data_quality(state: VpiState) -> VpiDataQuality:
    if state is VpiState.DATA_STALE:
        return VpiDataQuality.STALE
    if state is VpiState.DATA_INSUFFICIENT:
        return VpiDataQuality.INSUFFICIENT
    if state is VpiState.UNKNOWN:
        return VpiDataQuality.ERROR
    return VpiDataQuality.OK


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)
