from __future__ import annotations

from prep_watchdeck.domain.dto import ScannerRowDTO


def build_rankings(rows: list[ScannerRowDTO]) -> dict[str, list[dict[str, object]]]:
    return {"noTrade": [_no_trade_item(row) for row in rows if row.category == "NO_TRADE"]}


def _no_trade_item(row: ScannerRowDTO) -> dict[str, object]:
    return {
        "symbol": row.symbol,
        "category": row.category.value,
        "priorityScore": row.attention_score,
        "changePct": row.change_pct_by_tf.get("15m"),
        "volumeRatio": row.volume_ratio_by_tf.get("15m"),
        "turnoverUsdt": row.turnover_usdt_by_tf.get("15m"),
        "label": row.label,
    }
