from __future__ import annotations

from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.models import CandleBar


def turnover_usdt_by_timeframe(bars: list[CandleBar]) -> dict[str, float | None]:
    values: dict[str, float | None] = {}
    for timeframe, window in TIMEFRAME_BARS.items():
        if len(bars) < window:
            values[timeframe] = None
            continue
        values[timeframe] = sum(float(bar.quote_vol) for bar in bars[-window:])
    return values


def rolling_turnovers(bars: list[CandleBar], window: int) -> list[float]:
    if len(bars) < window:
        return []
    quotes = [float(bar.quote_vol) for bar in bars]
    return [sum(quotes[index - window : index]) for index in range(window, len(quotes) + 1)]
