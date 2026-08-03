from __future__ import annotations

from statistics import median

from prep_watchdeck.features.turnover import rolling_turnovers
from prep_watchdeck.models import CandleBar


def volume_ratio_15m(
    bars: list[CandleBar],
    baseline_window_bars: int,
    floor_usdt: float,
) -> float | None:
    window = 3
    if len(bars) < baseline_window_bars + window:
        return None
    current = sum(float(bar.quote_vol) for bar in bars[-window:])
    previous_bars = bars[:-window]
    candidates = rolling_turnovers(previous_bars, window)
    baseline_values = candidates[-baseline_window_bars:]
    if len(baseline_values) < baseline_window_bars:
        return None
    baseline = max(median(baseline_values), floor_usdt)
    return current / baseline if baseline > 0 else None


def volume_ratio_by_timeframe(
    bars: list[CandleBar],
    baseline_window_bars: int,
    floor_usdt: float,
) -> dict[str, float | None]:
    ratio_15m = volume_ratio_15m(bars, baseline_window_bars, floor_usdt)
    return {"5m": None, "15m": ratio_15m, "1h": None, "4h": None, "24h": None, "74h": None}
