from __future__ import annotations

from datetime import datetime

from prep_watchdeck_market.candles import (
    Candle1m,
    CandleParseError,
    decimal_value,
    non_negative_integer,
    require_mapping,
    require_text,
    timestamp_milliseconds,
)


def parse_aster_candle(payload: object, *, observed_at: datetime) -> Candle1m | None:
    root = require_mapping(payload, field_name="Aster candle event")
    event = (
        require_mapping(root.get("data"), field_name="Aster candle data")
        if "data" in root
        else root
    )
    kline = require_mapping(event.get("k"), field_name="Aster kline")
    closed = kline.get("x")
    if not isinstance(closed, bool):
        raise CandleParseError("Aster kline x must be boolean")
    if not closed:
        return None
    if kline.get("i") != "1m":
        raise CandleParseError("Aster candle interval must be 1m")
    source_symbol = require_text(kline.get("s"), field_name="Aster kline symbol")
    event_symbol = event.get("s")
    if event_symbol is not None and event_symbol != source_symbol:
        raise CandleParseError("Aster event and kline symbols differ")
    return Candle1m(
        venue="aster",
        source_symbol=source_symbol,
        bucket_start=timestamp_milliseconds(kline.get("t"), field_name="Aster kline start"),
        open_price=decimal_value(kline.get("o"), field_name="Aster open", positive=True),
        high_price=decimal_value(kline.get("h"), field_name="Aster high", positive=True),
        low_price=decimal_value(kline.get("l"), field_name="Aster low", positive=True),
        close_price=decimal_value(kline.get("c"), field_name="Aster close", positive=True),
        volume_base=decimal_value(kline.get("v"), field_name="Aster base volume"),
        volume_notional=decimal_value(kline.get("q"), field_name="Aster quote volume"),
        trade_count=non_negative_integer(kline.get("n"), field_name="Aster trade count"),
        finality="confirmed",
        source_at=timestamp_milliseconds(event.get("E"), field_name="Aster event time"),
        observed_at=observed_at,
    )
