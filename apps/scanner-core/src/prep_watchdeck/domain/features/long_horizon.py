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
    price_condition_matched: bool | None
    turnover_condition_matched: bool | None
    user_rule_74h_matched: bool | None


def compute_74h_features(
    bars: list[CandleBar],
    price_threshold_abs_pct: float = 4.0,
    volume_increase_threshold_pct: float = 15.0,
) -> LongHorizonFeatures:
    ordered = sorted(bars, key=lambda bar: bar.ts)
    if len(ordered) < MIN_REQUIRED_BARS:
        return LongHorizonFeatures(
            price_change_74h_pct=None,
            turnover_current_24h_usdt=None,
            turnover_24h_ending_74h_ago_usdt=None,
            volume_change_74h_24h_pct=None,
            price_condition_matched=None,
            turnover_condition_matched=None,
            user_rule_74h_matched=None,
        )

    current = ordered[-1]
    price_anchor = ordered[-1 - BARS_74H]
    price_change = None
    if _positive_finite(current.close) and _positive_finite(price_anchor.close):
        price_change = float((current.close / price_anchor.close - 1) * 100)

    current_24h = _sum_quote_vol(ordered[-BARS_24H:])
    historical_end = len(ordered) - BARS_74H
    historical_start = historical_end - BARS_24H
    historical_24h = _sum_quote_vol(ordered[historical_start:historical_end])
    volume_change = None
    if current_24h.is_finite() and _positive_finite(historical_24h):
        volume_change = float((current_24h / historical_24h - 1) * 100)

    price_match = None if price_change is None else abs(price_change) >= price_threshold_abs_pct
    volume_match = None if volume_change is None else volume_change >= volume_increase_threshold_pct
    composite = (
        None if price_match is None or volume_match is None else price_match and volume_match
    )
    return LongHorizonFeatures(
        price_change_74h_pct=price_change,
        turnover_current_24h_usdt=float(current_24h),
        turnover_24h_ending_74h_ago_usdt=float(historical_24h),
        volume_change_74h_24h_pct=volume_change,
        price_condition_matched=price_match,
        turnover_condition_matched=volume_match,
        user_rule_74h_matched=composite,
    )


def _sum_quote_vol(bars: list[CandleBar]) -> Decimal:
    return sum((bar.quote_vol for bar in bars), Decimal("0"))


def _positive_finite(value: Decimal) -> bool:
    return value.is_finite() and value > 0
