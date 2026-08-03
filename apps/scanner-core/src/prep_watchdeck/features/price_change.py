from __future__ import annotations

from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.models import CandleBar, Direction


def change_pct_by_timeframe(bars: list[CandleBar]) -> dict[str, float | None]:
    if not bars:
        return {tf: None for tf in TIMEFRAME_BARS}
    current = float(bars[-1].close)
    values: dict[str, float | None] = {}
    for timeframe, lookback in TIMEFRAME_BARS.items():
        if len(bars) <= lookback:
            values[timeframe] = None
            continue
        previous = float(bars[-1 - lookback].close)
        values[timeframe] = (current / previous - 1.0) * 100.0 if previous > 0 else None
    return values


def direction_from_change(
    change_15m: float | None,
    surge_threshold: float,
    move_threshold: float,
) -> Direction:
    if change_15m is None:
        return "FLAT"
    if change_15m >= surge_threshold:
        return "UP_SURGE"
    if change_15m >= move_threshold:
        return "UP"
    if change_15m <= -surge_threshold:
        return "DOWN_CRASH"
    if change_15m <= -move_threshold:
        return "DOWN"
    return "FLAT"
