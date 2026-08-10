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
    assert [item["symbol"] for item in rankings["noTrade"]] == ["THINUSDT"]


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


def test_display_only_hour_volume_ratios_do_not_populate_candidate_rankings() -> None:
    rows = [_row("ALTUSDT", Category.WATCH, 2.0, 5.0, volume_1h=9.0, volume_4h=8.0)]

    rankings = build_rankings(rows, top_n=5)

    assert rankings["timeframes"]["1h"]["volumeUp"] == []
    assert rankings["timeframes"]["4h"]["volumeUp"] == []
    assert rankings["meta"]["timeframes"]["1h"]["volumeUp"]["totalEligible"] == 0
    assert rankings["meta"]["timeframes"]["4h"]["volumeUp"]["totalEligible"] == 0


def _row(
    symbol: str,
    category: Category,
    change_15m: float,
    volume_15m: float | None,
    *,
    matched: bool | None = True,
    volume_1h: float | None = None,
    volume_4h: float | None = None,
) -> ScannerRowDTO:
    return ScannerRowDTO(
        symbol=symbol,
        ts=1_781_000_000_000,
        category=category,
        label="TEST",
        attention_score=50,
        change_pct_by_tf={"15m": change_15m},
        turnover_usdt_by_tf={"15m": 10000},
        volume_ratio_by_tf={"15m": volume_15m, "1h": volume_1h, "4h": volume_4h},
        data_quality=DataQuality.OK,
        reason_codes=["TEST"],
        user_rule_74h_matched=matched,
        risk_tag_codes=[],
    )


def test_rankings_gate_timeframes_but_preserve_no_trade_diagnostics() -> None:
    rows = [
        _row("MATCHUSDT", Category.WATCH, 5.0, 5.0, matched=True),
        _row("MISSUSDT", Category.CAUTION, 4.0, 4.0, matched=False),
        _row("UNKNOWNUSDT", Category.WATCH, 3.0, 3.0, matched=None),
        _row("THINUSDT", Category.NO_TRADE, 20.0, 99.0, matched=None),
    ]

    rankings = build_rankings(rows, top_n=5)

    assert [item["symbol"] for item in rankings["timeframes"]["15m"]["changeUp"]] == ["MATCHUSDT"]
    assert rankings["meta"]["timeframes"]["15m"]["changeUp"]["totalEligible"] == 1
    assert [item["symbol"] for item in rankings["noTrade"]] == ["THINUSDT"]
