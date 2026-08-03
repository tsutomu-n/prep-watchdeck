from __future__ import annotations

from typing import Any

from prep_watchdeck.constants import TIMEFRAME_BARS
from prep_watchdeck.models import ScannerRow


def _row_item(row: ScannerRow, timeframe: str) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "category": row.category,
        "priorityScore": row.priority_score,
        "changePct": row.change_pct_by_tf.get(timeframe),
        "volumeRatio": row.volume_ratio_by_tf.get(timeframe),
        "turnoverUsdt": row.turnover_usdt_by_tf.get(timeframe),
        "label": row.label,
    }


def build_rankings(
    rows: list[ScannerRow],
    top_n: int,
    exclude_no_trade: bool = True,
) -> dict[str, Any]:
    source = [row for row in rows if row.category != "NO_TRADE"] if exclude_no_trade else rows
    timeframes: dict[str, dict[str, list[dict[str, object]]]] = {}
    for timeframe in TIMEFRAME_BARS:
        by_change_up = sorted(
            [row for row in source if row.change_pct_by_tf.get(timeframe) is not None],
            key=lambda row: row.change_pct_by_tf[timeframe] or 0.0,
            reverse=True,
        )
        by_change_down = sorted(
            [row for row in source if row.change_pct_by_tf.get(timeframe) is not None],
            key=lambda row: row.change_pct_by_tf[timeframe] or 0.0,
        )
        by_volume = sorted(
            [row for row in source if row.volume_ratio_by_tf.get(timeframe) is not None],
            key=lambda row: row.volume_ratio_by_tf[timeframe] or 0.0,
            reverse=True,
        )
        by_turnover = sorted(
            [row for row in source if row.turnover_usdt_by_tf.get(timeframe) is not None],
            key=lambda row: row.turnover_usdt_by_tf[timeframe] or 0.0,
            reverse=True,
        )
        timeframes[timeframe] = {
            "changeUp": [_row_item(row, timeframe) for row in by_change_up[:top_n]],
            "changeDown": [_row_item(row, timeframe) for row in by_change_down[:top_n]],
            "volumeUp": [_row_item(row, timeframe) for row in by_volume[:top_n]],
            "turnoverTop": [_row_item(row, timeframe) for row in by_turnover[:top_n]],
        }
    return {
        "timeframes": timeframes,
        "noTrade": [_row_item(row, "15m") for row in rows if row.category == "NO_TRADE"],
    }
