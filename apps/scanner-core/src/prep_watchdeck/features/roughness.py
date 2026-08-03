from __future__ import annotations

from itertools import pairwise

from prep_watchdeck.models import CandleBar


def move_concentration_15m(bars: list[CandleBar]) -> float | None:
    if len(bars) < 4:
        return None
    returns = []
    recent = bars[-4:]
    for previous, current in pairwise(recent):
        previous_close = float(previous.close)
        move = abs(float(current.close) / previous_close - 1.0) if previous_close > 0 else 0.0
        returns.append(move)
    total = sum(returns)
    if total <= 0:
        return 0.0
    return max(returns) / total


def classify_roughness_15m(
    bars: list[CandleBar],
    warn_threshold: float,
    avoid_threshold: float,
) -> str:
    concentration = move_concentration_15m(bars)
    if concentration is None:
        return "UNKNOWN"
    if concentration <= warn_threshold:
        return "NORMAL"
    if concentration <= avoid_threshold:
        return "WARN"
    return "TOO_ROUGH"
