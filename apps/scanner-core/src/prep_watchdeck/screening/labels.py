from __future__ import annotations

from prep_watchdeck.config.filter_config import FilterConfig


def choose_label(
    config: FilterConfig,
    change_15m: float | None,
    volume_ratio_15m: float | None,
    turnover_15m: float | None,
    roughness_15m: str,
) -> str:
    change = change_15m or 0.0
    volume_ratio = volume_ratio_15m or 0.0
    turnover = turnover_15m or 0.0
    if (
        abs(change) >= config.price_change.surge_15m_pct
        and turnover < config.turnover.min_turnover_15m_usdt
    ):
        return "THIN_SPIKE"
    if roughness_15m == "TOO_ROUGH":
        return "TOO_ROUGH"
    if (
        change >= config.price_change.move_15m_pct
        and volume_ratio >= config.volume.min_volume_ratio
        and turnover >= config.turnover.min_turnover_15m_usdt
    ):
        return "VOLUME_CONFIRMED_UP"
    if (
        change <= -config.price_change.move_15m_pct
        and volume_ratio >= config.volume.min_volume_ratio
        and turnover >= config.turnover.min_turnover_15m_usdt
    ):
        return "VOLUME_CONFIRMED_DOWN"
    if (
        volume_ratio >= config.volume.volume_leading_ratio
        and abs(change) < config.price_change.move_15m_pct
        and turnover >= config.turnover.min_turnover_15m_usdt
    ):
        return "VOLUME_LEADING"
    if (
        abs(change) >= config.price_change.surge_15m_pct
        and volume_ratio < config.volume.min_volume_ratio
    ):
        return "PRICE_LEADING_WEAK_VOLUME"
    return "LOW_REACTION"
