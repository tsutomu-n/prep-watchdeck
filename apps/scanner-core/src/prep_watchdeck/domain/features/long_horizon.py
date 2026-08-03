from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from prep_watchdeck.models import CandleBar

BARS_74H = 74 * 12
BARS_24H = 24 * 12
MIN_REQUIRED_BARS = BARS_74H + BARS_24H + 1


@dataclass(frozen=True)
class LongHorizonFeatures:
    price_change_74h_pct: float | None
    turnover_current_24h_usdt: float | None
    turnover_24h_ending_74h_ago_usdt: float | None
    volume_change_74h_24h_pct: float | None
    user_rule_74h_matched: bool | None


def compute_74h_features(
    bars: list[CandleBar],
    price_threshold_abs_pct: float = 4.0,
    volume_increase_threshold_pct: float = 15.0,
) -> LongHorizonFeatures:
    ordered = sorted(bars, key=lambda bar: bar.ts)
    if len(ordered) < MIN_REQUIRED_BARS:
        return LongHorizonFeatures(None, None, None, None, None)

    current = ordered[-1]
    price_anchor = ordered[-1 - BARS_74H]
    price_change = float((current.close / price_anchor.close - 1) * 100)

    current_24h = _sum_quote_vol(ordered[-BARS_24H:])
    historical_end = len(ordered) - BARS_74H
    historical_start = historical_end - BARS_24H
    historical_24h = _sum_quote_vol(ordered[historical_start:historical_end])
    volume_change = None
    if historical_24h > 0:
        volume_change = float((current_24h / historical_24h - 1) * 100)

    price_match = abs(price_change) >= price_threshold_abs_pct
    volume_match = volume_change is not None and volume_change >= volume_increase_threshold_pct
    return LongHorizonFeatures(
        price_change_74h_pct=price_change,
        turnover_current_24h_usdt=float(current_24h),
        turnover_24h_ending_74h_ago_usdt=float(historical_24h),
        volume_change_74h_24h_pct=volume_change,
        user_rule_74h_matched=price_match or volume_match,
    )


def _sum_quote_vol(bars: list[CandleBar]) -> Decimal:
    return sum((bar.quote_vol for bar in bars), Decimal("0"))
