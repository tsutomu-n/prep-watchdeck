from __future__ import annotations

from decimal import Decimal

import pytest

from prep_watchdeck.models import CandleBar


@pytest.fixture
def make_bars():
    def _make_bars(count: int, quote_vol: Decimal = Decimal("1000")) -> list[CandleBar]:
        start = 1_781_000_000_000
        bars: list[CandleBar] = []
        for i in range(count):
            price = Decimal("1.0") + Decimal(i) * Decimal("0.0001")
            bars.append(
                CandleBar(
                    symbol="ALTUSDT",
                    ts=start + i * 300_000,
                    open=price,
                    high=price * Decimal("1.01"),
                    low=price * Decimal("0.99"),
                    close=price,
                    base_vol=Decimal("100"),
                    quote_vol=quote_vol,
                )
            )
        return bars

    return _make_bars
