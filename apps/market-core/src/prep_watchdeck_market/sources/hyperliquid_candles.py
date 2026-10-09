from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from prep_watchdeck_market.candles import (
    Candle1m,
    CandleParseError,
    decimal_value,
    non_negative_integer,
    require_mapping,
    require_text,
    require_utc_datetime,
    timestamp_milliseconds,
)
from prep_watchdeck_market.models import Venue

DERIVED_FINAL_DELAY = timedelta(seconds=5)


class HyperliquidCandleFinalizer:
    def __init__(self) -> None:
        self._pending: dict[tuple[Venue, str, datetime], Candle1m] = {}

    def ingest(self, payload: object, *, observed_at: datetime) -> None:
        candle = _parse_hyperliquid_candidate(payload, observed_at=observed_at)
        # Later same-bucket receipts are corrections, including after emission.
        # Canonical storage keeps its existing newest-receipt/finality precedence.
        previous = self._pending.get(candle.storage_key)
        if previous is None or candle.observed_at > previous.observed_at:
            self._pending[candle.storage_key] = candle

    def finalize(self, *, now: datetime) -> tuple[Candle1m, ...]:
        require_utc_datetime(now, field_name="Hyperliquid finalization time")
        eligible = sorted(
            (
                candle
                for candle in self._pending.values()
                if max(candle.bucket_end + DERIVED_FINAL_DELAY, candle.observed_at) <= now
            ),
            key=lambda candle: candle.storage_key,
        )
        for candle in eligible:
            self._pending.pop(candle.storage_key)
        return tuple(replace(candle, finalized_at=now) for candle in eligible)

    @property
    def pending_count(self) -> int:
        return len(self._pending)


def _parse_hyperliquid_candidate(payload: object, *, observed_at: datetime) -> Candle1m:
    root = require_mapping(payload, field_name="Hyperliquid candle event")
    if "channel" in root and root.get("channel") != "candle":
        raise CandleParseError("Hyperliquid event channel must be candle")
    data = require_mapping(root.get("data"), field_name="Hyperliquid candle data")
    if data.get("i") != "1m":
        raise CandleParseError("Hyperliquid candle interval must be 1m")
    return Candle1m(
        venue="hyperliquid",
        source_symbol=require_text(data.get("s"), field_name="Hyperliquid symbol"),
        bucket_start=timestamp_milliseconds(data.get("t"), field_name="Hyperliquid start"),
        open_price=decimal_value(data.get("o"), field_name="Hyperliquid open", positive=True),
        high_price=decimal_value(data.get("h"), field_name="Hyperliquid high", positive=True),
        low_price=decimal_value(data.get("l"), field_name="Hyperliquid low", positive=True),
        close_price=decimal_value(data.get("c"), field_name="Hyperliquid close", positive=True),
        volume_base=decimal_value(data.get("v"), field_name="Hyperliquid base volume"),
        volume_notional=None,
        trade_count=non_negative_integer(data.get("n"), field_name="Hyperliquid trade count"),
        finality="derived_final",
        source_at=timestamp_milliseconds(data.get("T"), field_name="Hyperliquid end"),
        observed_at=observed_at,
    )
