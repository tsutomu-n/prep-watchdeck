from __future__ import annotations

from math import isfinite
from statistics import median

from prep_watchdeck.features.turnover import rolling_turnovers
from prep_watchdeck.models import CandleBar

VOLUME_RATIO_WINDOW_MINUTES = 15
VOLUME_RATIO_SAMPLE_STEP_MINUTES = 5


def volume_ratio_15m_metadata(
    baseline_sample_count: int,
    floor_usdt: float,
) -> dict[str, int | float | str]:
    return {
        "windowMinutes": VOLUME_RATIO_WINDOW_MINUTES,
        "sampleStepMinutes": VOLUME_RATIO_SAMPLE_STEP_MINUTES,
        "baselineSampleCount": baseline_sample_count,
        "approxBaselineSpanMinutes": baseline_sample_count * VOLUME_RATIO_SAMPLE_STEP_MINUTES,
        "statistic": "median",
        "floorUsdt": floor_usdt,
    }


def volume_ratio_15m(
    bars: list[CandleBar],
    baseline_window_bars: int,
    floor_usdt: float,
) -> float | None:
    return _volume_ratio(bars, 3, baseline_window_bars, floor_usdt)


def _volume_ratio(
    bars: list[CandleBar],
    window: int,
    baseline_sample_count: int,
    floor_usdt: float,
) -> float | None:
    if window <= 0 or baseline_sample_count <= 0 or not isfinite(floor_usdt):
        return None
    required_bars = baseline_sample_count + (window * 2) - 1
    if len(bars) < required_bars:
        return None
    current = sum(float(bar.quote_vol) for bar in bars[-window:])
    if not isfinite(current):
        return None
    previous_bars = bars[:-window]
    candidates = rolling_turnovers(previous_bars, window)
    baseline_values = candidates[-baseline_sample_count:]
    if len(baseline_values) < baseline_sample_count or any(
        not isfinite(value) for value in baseline_values
    ):
        return None
    baseline = max(median(baseline_values), floor_usdt)
    if not isfinite(baseline) or baseline <= 0:
        return None
    ratio = current / baseline
    return ratio if isfinite(ratio) else None


def volume_ratio_by_timeframe(
    bars: list[CandleBar],
    baseline_window_bars: int,
    floor_usdt: float,
) -> dict[str, float | None]:
    return {
        "5m": None,
        "15m": volume_ratio_15m(bars, baseline_window_bars, floor_usdt),
        "1h": _volume_ratio(bars, 12, baseline_window_bars, floor_usdt),
        "4h": _volume_ratio(bars, 48, baseline_window_bars, floor_usdt),
        "24h": None,
        "74h": None,
    }
