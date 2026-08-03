from __future__ import annotations

from prep_watchdeck.models import TickerInfo


def funding_rate_from_ticker(ticker: TickerInfo) -> float | None:
    return float(ticker.funding_rate) if ticker.funding_rate is not None else None
