from __future__ import annotations

from datetime import datetime

from prep_watchdeck_market.candles import (
    Candle1m,
    CandleParseError,
    decimal_value,
    optional_timestamp_milliseconds,
    require_list,
    require_mapping,
    timestamp_milliseconds,
)


def parse_bitget_finished_candles(
    payload: object,
    *,
    source_symbol: str,
    observed_at: datetime,
) -> tuple[Candle1m, ...]:
    root = require_mapping(payload, field_name="Bitget finished candles")
    if root.get("code") != "00000":
        raise CandleParseError("Bitget finished candles returned a non-success code")
    rows = require_list(root.get("data"), field_name="Bitget finished candle data")
    source_at = optional_timestamp_milliseconds(
        root.get("requestTime"), field_name="Bitget requestTime"
    )
    by_key: dict[tuple[object, ...], Candle1m] = {}
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            raise CandleParseError("Bitget finished candle row must contain seven values")
        candle = Candle1m(
            venue="bitget",
            source_symbol=source_symbol,
            bucket_start=timestamp_milliseconds(row[0], field_name="Bitget candle timestamp"),
            open_price=decimal_value(row[1], field_name="Bitget open", positive=True),
            high_price=decimal_value(row[2], field_name="Bitget high", positive=True),
            low_price=decimal_value(row[3], field_name="Bitget low", positive=True),
            close_price=decimal_value(row[4], field_name="Bitget close", positive=True),
            volume_base=decimal_value(row[5], field_name="Bitget base volume"),
            volume_notional=decimal_value(row[6], field_name="Bitget quote volume"),
            trade_count=None,
            finality="confirmed",
            source_at=source_at,
            observed_at=observed_at,
        )
        by_key[candle.storage_key] = candle
    return tuple(sorted(by_key.values(), key=lambda item: item.bucket_start)[-3:])
