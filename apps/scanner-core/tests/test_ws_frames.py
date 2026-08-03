from __future__ import annotations

import pytest

from prep_watchdeck.application.ws_frames import (
    ChannelSpec,
    ParsedWsFrame,
    build_channel_specs,
    parse_ws_frame,
    shard_channel_specs,
)


def test_parse_ticker_frame_maps_official_fields() -> None:
    parsed = parse_ws_frame(
        {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "ticker",
                "instId": "BTCUSDT",
            },
            "data": [
                {
                    "symbol": "BTCUSDT",
                    "ts": "1781000000123",
                    "lastPr": "101.5",
                    "bidPr": "101.4",
                    "askPr": "101.6",
                    "high24h": "110.0",
                    "low24h": "90.0",
                    "change24h": "0.05",
                    "fundingRate": "0.0001",
                    "nextFundingTime": "1781003600000",
                    "markPrice": "101.55",
                    "indexPrice": "101.50",
                    "holdingAmount": "123456",
                    "baseVolume": "1000",
                    "quoteVolume": "101500",
                    "openUtc": "100.0",
                }
            ],
            "ts": "1781000000456",
        }
    )

    assert parsed.candles_1m == []
    assert len(parsed.tickers) == 1
    ticker = parsed.tickers[0]
    assert ticker.symbol == "BTCUSDT"
    assert ticker.ts_ms == 1_781_000_000_123
    assert ticker.last_price == 101.5
    assert ticker.bid_price == 101.4
    assert ticker.ask_price == 101.6
    assert ticker.high_24h == 110.0
    assert ticker.low_24h == 90.0
    assert ticker.change_24h == 0.05
    assert ticker.funding_rate == 0.0001
    assert ticker.next_funding_time_ms == 1_781_003_600_000
    assert ticker.mark_price == 101.55
    assert ticker.index_price == 101.5
    assert ticker.holding_amount == 123456.0
    assert ticker.base_volume_24h == 1000.0
    assert ticker.quote_volume_24h == 101500.0
    assert ticker.open_utc == 100.0
    assert ticker.updated_at_ms == 1_781_000_000_456


def test_parse_candle1m_frame_maps_volumes_and_closed_flag() -> None:
    parsed = parse_ws_frame(
        {
            "arg": {
                "instType": "USDT-FUTURES",
                "channel": "candle1m",
                "instId": "ETHUSDT",
            },
            "data": [
                [
                    "1781000040000",
                    "2500.0",
                    "2520.0",
                    "2490.0",
                    "2510.0",
                    "12.5",
                    "31375.0",
                    "31376.0",
                    "1",
                ]
            ],
            "ts": "1781000040500",
        }
    )

    assert parsed.tickers == []
    assert len(parsed.candles_1m) == 1
    candle = parsed.candles_1m[0]
    assert candle.symbol == "ETHUSDT"
    assert candle.ts_ms == 1_781_000_040_000
    assert candle.open == 2500.0
    assert candle.high == 2520.0
    assert candle.low == 2490.0
    assert candle.close == 2510.0
    assert candle.base_volume == 12.5
    assert candle.quote_volume == 31375.0
    assert candle.usdt_volume == 31376.0
    assert candle.is_closed is True
    assert candle.source == "ws-candle1m"
    assert candle.updated_at_ms == 1_781_000_040_500


def test_parse_ws_frame_ignores_ack_rejects_errors_and_unknown_market_data() -> None:
    assert (
        parse_ws_frame(
            {
                "event": "subscribe",
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": "BTCUSDT",
                },
            }
        )
        == ParsedWsFrame()
    )

    with pytest.raises(ValueError, match="websocket error 30003: symbol not found"):
        parse_ws_frame(
            {
                "event": "error",
                "code": "30003",
                "msg": "symbol not found",
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "ticker",
                    "instId": "BADUSDT",
                },
            }
        )

    with pytest.raises(ValueError, match="unsupported websocket channel"):
        parse_ws_frame(
            {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "books",
                    "instId": "BTCUSDT",
                },
                "data": [{"unexpected": "payload"}],
            }
        )


def test_build_channel_specs_and_shards_under_bitget_channel_limit() -> None:
    specs = build_channel_specs(["ethusdt", " BTCUSDT "])

    assert specs == [
        ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="BTCUSDT"),
        ChannelSpec(inst_type="USDT-FUTURES", channel="candle1m", inst_id="BTCUSDT"),
        ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id="ETHUSDT"),
        ChannelSpec(inst_type="USDT-FUTURES", channel="candle1m", inst_id="ETHUSDT"),
    ]

    many_specs = [
        ChannelSpec(inst_type="USDT-FUTURES", channel="ticker", inst_id=f"SYM{i}USDT")
        for i in range(101)
    ]
    shards = shard_channel_specs(many_specs)

    assert [len(shard) for shard in shards] == [48, 48, 5]

    with pytest.raises(ValueError, match="max_channels must be between 1 and 49"):
        shard_channel_specs(many_specs, max_channels=50)
