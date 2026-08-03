from __future__ import annotations

from prep_watchdeck.models import TickerInfo


def open_interest_from_ticker(ticker: TickerInfo) -> float | None:
    return float(ticker.holding_amount) if ticker.holding_amount is not None else None
