from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from prep_watchdeck.adapters.bitget_live.provider import snapshot_from_pipeline
from prep_watchdeck.config.templates import load_template
from prep_watchdeck.models import CandleBar, Category, ContractInfo, ScannerRow, TickerInfo
from prep_watchdeck.screening.pipeline import PipelineResult


def test_snapshot_from_pipeline_marks_live_and_builds_rankings() -> None:
    bars = [
        CandleBar(
            symbol="ALTUSDT",
            ts=1_781_000_000_000 + index * 300_000,
            open=Decimal("1.0"),
            high=Decimal("1.2"),
            low=Decimal("0.9"),
            close=Decimal("1.0") + Decimal(index) * Decimal("0.01"),
            base_vol=Decimal("100"),
            quote_vol=Decimal("1000"),
        )
        for index in range(20)
    ]
    result = PipelineResult(
        run_id="live-test",
        generated_at_ms=1_781_000_000_000,
        rows=[
            ScannerRow(
                symbol="ALTUSDT",
                ts=bars[-1].ts,
                close=bars[-1].close,
                category="WATCH",
                direction="UP",
                label="VOLUME_CONFIRMED_UP",
                priority_score=80.0,
                change_pct_by_tf={"15m": 2.0},
                turnover_usdt_by_tf={"15m": 5000.0},
                volume_ratio_by_tf={"15m": 3.0},
                roughness_15m="NORMAL",
                btc_relative_15m="STRONG",
                funding_bias="NEUTRAL",
                open_interest_state="UNKNOWN",
                reason="VOLUME_CONFIRMED_UP",
                risk_tags=[],
                data_quality="OK",
            )
        ],
        contracts=[
            ContractInfo.model_validate(
                {
                    "symbol": "ALTUSDT",
                    "productType": "USDT-FUTURES",
                    "symbolType": "perpetual",
                    "symbolStatus": "normal",
                    "minTradeUSDT": "5",
                    "maxLever": "25",
                }
            )
        ],
        tickers=[
            TickerInfo.model_validate(
                {
                    "symbol": "ALTUSDT",
                    "lastPr": "1.19",
                    "high24h": "1.40",
                    "low24h": "0.80",
                    "usdtVolume": "1000000",
                }
            )
        ],
        candles_by_symbol={"ALTUSDT": bars},
        chart_candles_by_symbol={
            "ALTUSDT": {
                "5m": bars[-5:],
                "15m": bars[-3:],
                "1h": bars[-12:],
                "4h": bars,
                "24h": bars,
                "74h": bars,
            }
        },
        candle_errors={},
    )

    snapshot = snapshot_from_pipeline(
        result,
        template="balanced",
        product_type="USDT-FUTURES",
        sparkline_points_limit=128,
    )

    assert snapshot.source.data_source == "live"
    assert snapshot.summary["counts"]["WATCH"] == 1
    assert snapshot.rows[0].symbol == "ALTUSDT"
    assert snapshot.rows[0].last_price == 1.19
    assert snapshot.rows[0].range_24h_high == 1.4
    assert snapshot.rows[0].range_24h_low == 0.8
    assert snapshot.rows[0].range_24h_position_pct == 65.0
    assert snapshot.rows[0].range_24h_pct == 75.0
    assert snapshot.rows[0].sparkline is not None
    assert len(snapshot.rows[0].sparkline["points"]) == 16
    assert len(snapshot.rows[0].sparkline["bars"]) == 16
    assert all(
        len(timeframe_bars) <= 16
        for timeframe_bars in snapshot.rows[0].sparkline["timeframes"].values()
    )
    assert len(snapshot.rows[0].sparkline["timeframes"]["4h"]) == 16
    assert snapshot.rows[0].sparkline["bars"][-1] == {
        "ts": bars[-1].ts,
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": 1.19,
        "quoteVolume": 1000.0,
    }
    assert snapshot.rows[0].sparkline["timeframes"]["15m"][-1] == {
        "ts": bars[-1].ts,
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": 1.19,
        "quoteVolume": 1000.0,
    }
    assert snapshot.rankings["timeframes"]["15m"]["changeUp"][0]["symbol"] == "ALTUSDT"


def test_snapshot_from_pipeline_uses_ranking_top_n_from_config() -> None:
    config = load_template(Path("../../config/scanner-filters"), "balanced")
    config = config.model_copy(update={"ranking": config.ranking.model_copy(update={"top_n": 1})})
    result = PipelineResult(
        run_id="ranking-top-n-test",
        generated_at_ms=1_781_000_000_000,
        rows=[
            scanner_row("ALTUSDT", "WATCH", 2.0),
            scanner_row("BETUSDT", "WATCH", 4.0),
            scanner_row("THINUSDT", "NO_TRADE", 20.0),
        ],
        contracts=[],
        tickers=[],
        candles_by_symbol={},
        chart_candles_by_symbol={},
        candle_errors={},
    )

    snapshot = snapshot_from_pipeline(
        result, template="balanced", config=config, product_type="USDT-FUTURES"
    )

    assert [item["symbol"] for item in snapshot.rankings["timeframes"]["15m"]["changeUp"]] == [
        "BETUSDT"
    ]
    assert snapshot.rankings["meta"]["timeframes"]["15m"]["changeUp"] == {
        "limit": 1,
        "totalEligible": 2,
        "excludedNoTrade": True,
    }


def scanner_row(symbol: str, category: Category, change_15m: float) -> ScannerRow:
    return ScannerRow(
        symbol=symbol,
        ts=1_781_000_000_000,
        close=Decimal("1.0"),
        category=category,
        direction="UP",
        label="VOLUME_CONFIRMED_UP",
        priority_score=80.0,
        change_pct_by_tf={"15m": change_15m},
        turnover_usdt_by_tf={"15m": 5000.0},
        volume_ratio_by_tf={"15m": 3.0},
        roughness_15m="NORMAL",
        btc_relative_15m="STRONG",
        funding_bias="NEUTRAL",
        open_interest_state="UNKNOWN",
        reason="VOLUME_CONFIRMED_UP",
        risk_tags=[],
        data_quality="OK",
    )
