from prep_watchdeck.domain.market_comparison import (
    MARKET_COMPARISON_SOURCES,
    MarketPriceObservation,
    build_market_comparison,
)


def test_build_market_comparison_requires_three_fresh_prices() -> None:
    generated_at_ms = 1_780_000_000_000
    observations = [
        MarketPriceObservation(
            source=source,
            symbol="BTCUSDT",
            source_symbol="BTC" if source == "hyperliquid" else "BTCUSDT",
            quote="USD" if source == "hyperliquid" else "USDT",
            mark_price=price,
            observed_at_ms=generated_at_ms,
        )
        for source, price in zip(MARKET_COMPARISON_SOURCES, [100.0, 101.0, 102.0], strict=True)
    ]

    block = build_market_comparison(observations, generated_at_ms=generated_at_ms)
    btc = block["symbols"][0]

    assert btc["status"] == "ready"
    assert btc["coverage"] == {"valid": 3, "required": 3}
    assert btc["medianMarkPrice"] == 101.0
    assert btc["spreadPct"] == (2.0 / 101.0 * 100)


def test_build_market_comparison_hides_median_when_a_source_is_missing() -> None:
    generated_at_ms = 1_780_000_000_000
    observations = [
        MarketPriceObservation(
            source="bitget",
            symbol="BTCUSDT",
            source_symbol="BTCUSDT",
            quote="USDT",
            mark_price=100.0,
            observed_at_ms=generated_at_ms,
        ),
        MarketPriceObservation(
            source="bybit",
            symbol="BTCUSDT",
            source_symbol="BTCUSDT",
            quote="USDT",
            mark_price=102.0,
            observed_at_ms=generated_at_ms,
        ),
    ]

    block = build_market_comparison(
        observations,
        generated_at_ms=generated_at_ms,
        errors={"hyperliquid": "TimeoutError"},
    )
    btc = block["symbols"][0]

    assert btc["status"] == "incomplete"
    assert btc["coverage"] == {"valid": 2, "required": 3}
    assert btc["medianMarkPrice"] is None
    assert btc["spreadPct"] is None
    hyperliquid = next(item for item in btc["sources"] if item["source"] == "hyperliquid")
    assert hyperliquid["error"] == "TimeoutError"


def test_build_market_comparison_rejects_a_stale_source_timestamp() -> None:
    generated_at_ms = 1_780_000_000_000
    observations = [
        MarketPriceObservation(
            source=source,
            symbol="BTCUSDT",
            source_symbol="BTC" if source == "hyperliquid" else "BTCUSDT",
            quote="USD" if source == "hyperliquid" else "USDT",
            mark_price=price,
            observed_at_ms=generated_at_ms,
            source_at_ms=(generated_at_ms - 11 * 60_000 if source == "bitget" else generated_at_ms),
        )
        for source, price in zip(MARKET_COMPARISON_SOURCES, [100.0, 101.0, 102.0], strict=True)
    ]

    block = build_market_comparison(observations, generated_at_ms=generated_at_ms)
    btc = block["symbols"][0]

    assert btc["coverage"] == {"valid": 2, "required": 3}
    assert btc["medianMarkPrice"] is None
