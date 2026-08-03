from __future__ import annotations

from prep_watchdeck.domain.dto import ScannerRowDTO
from prep_watchdeck.domain.enums import Category, DataQuality
from prep_watchdeck.domain.screening.rankings import build_rankings


def test_rankings_exclude_no_trade_and_sort() -> None:
    rows = [
        _row("ALTUSDT", Category.WATCH, 2.0, 5.0),
        _row("BETUSDT", Category.CAUTION, 4.0, 3.0),
        _row("THINUSDT", Category.NO_TRADE, 20.0, 99.0),
    ]

    rankings = build_rankings(rows, top_n=5)

    change_up = rankings["timeframes"]["15m"]["changeUp"]
    volume_up = rankings["timeframes"]["15m"]["volumeUp"]
    assert [item["symbol"] for item in change_up] == ["BETUSDT", "ALTUSDT"]
    assert [item["symbol"] for item in volume_up] == ["ALTUSDT", "BETUSDT"]
    assert rankings["meta"]["timeframes"]["15m"]["changeUp"] == {
        "limit": 5,
        "totalEligible": 2,
        "excludedNoTrade": True,
    }


def test_rankings_limit_items_but_keep_total_eligible() -> None:
    rows = [
        _row("ALTUSDT", Category.WATCH, 2.0, 5.0),
        _row("BETUSDT", Category.CAUTION, 4.0, 3.0),
        _row("THINUSDT", Category.NO_TRADE, 20.0, 99.0),
    ]

    rankings = build_rankings(rows, top_n=1)

    assert [item["symbol"] for item in rankings["timeframes"]["15m"]["changeUp"]] == ["BETUSDT"]
    assert rankings["meta"]["timeframes"]["15m"]["changeUp"] == {
        "limit": 1,
        "totalEligible": 2,
        "excludedNoTrade": True,
    }


def test_rankings_total_eligible_counts_metric_values_only() -> None:
    rows = [
        _row("ALTUSDT", Category.WATCH, 2.0, 5.0),
        _row("BETUSDT", Category.CAUTION, 4.0, None),
        _row("THINUSDT", Category.NO_TRADE, 20.0, 99.0),
    ]

    rankings = build_rankings(rows, top_n=5)

    assert rankings["meta"]["timeframes"]["15m"]["changeUp"]["totalEligible"] == 2
    assert rankings["meta"]["timeframes"]["15m"]["volumeUp"]["totalEligible"] == 1


def _row(
    symbol: str, category: Category, change_15m: float, volume_15m: float | None
) -> ScannerRowDTO:
    return ScannerRowDTO(
        symbol=symbol,
        ts=1_781_000_000_000,
        category=category,
        label="TEST",
        attention_score=50,
        change_pct_by_tf={"15m": change_15m},
        turnover_usdt_by_tf={"15m": 10000},
        volume_ratio_by_tf={"15m": volume_15m},
        data_quality=DataQuality.OK,
        reason_codes=["TEST"],
        risk_tag_codes=[],
    )
