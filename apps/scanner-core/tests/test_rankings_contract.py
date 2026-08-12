from __future__ import annotations

from prep_watchdeck.domain.dto import ScannerRowDTO
from prep_watchdeck.domain.enums import Category, DataQuality
from prep_watchdeck.domain.screening.rankings import build_rankings


def test_rankings_publish_only_no_trade_diagnostics() -> None:
    rows = [
        _row("ALTUSDT", Category.WATCH, 2.0),
        _row("THINUSDT", Category.NO_TRADE, 20.0),
    ]

    rankings = build_rankings(rows)

    assert set(rankings) == {"noTrade"}
    assert rankings["noTrade"] == [
        {
            "symbol": "THINUSDT",
            "category": "NO_TRADE",
            "priorityScore": 50.0,
            "changePct": 20.0,
            "volumeRatio": 5.0,
            "turnoverUsdt": 10000.0,
            "label": "TEST",
        }
    ]


def _row(symbol: str, category: Category, change_15m: float) -> ScannerRowDTO:
    return ScannerRowDTO(
        symbol=symbol,
        ts=1_781_000_000_000,
        category=category,
        label="TEST",
        attention_score=50,
        change_pct_by_tf={"15m": change_15m},
        turnover_usdt_by_tf={"15m": 10000.0},
        volume_ratio_by_tf={"15m": 5.0},
        data_quality=DataQuality.OK,
        reason_codes=["TEST"],
        risk_tag_codes=[],
    )
