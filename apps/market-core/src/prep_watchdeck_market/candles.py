from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal

from prep_watchdeck_market.models import Venue

CandleFinality = Literal["confirmed", "derived_final"]


class CandleParseError(ValueError):
    """A candle payload is incomplete or violates the normalized 1-minute contract."""


@dataclass(frozen=True, slots=True)
class Candle1m:
    venue: Venue
    source_symbol: str
    bucket_start: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume_base: Decimal | None
    volume_notional: Decimal | None
    trade_count: int | None
    finality: CandleFinality
    source_at: datetime | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.source_symbol.strip():
            raise CandleParseError("source_symbol must not be empty")
        require_utc_datetime(self.bucket_start, field_name="bucket_start")
        if self.bucket_start.second != 0 or self.bucket_start.microsecond != 0:
            raise CandleParseError("bucket_start must be aligned to one minute")
        require_utc_datetime(self.observed_at, field_name="observed_at")
        if self.source_at is not None:
            require_utc_datetime(self.source_at, field_name="source_at")
        for field_name, value in (
            ("open_price", self.open_price),
            ("high_price", self.high_price),
            ("low_price", self.low_price),
            ("close_price", self.close_price),
        ):
            if not value.is_finite() or value <= 0:
                raise CandleParseError(f"{field_name} must be a positive finite decimal")
        if self.high_price < max(self.open_price, self.close_price, self.low_price):
            raise CandleParseError("high_price is below another OHLC value")
        if self.low_price > min(self.open_price, self.close_price, self.high_price):
            raise CandleParseError("low_price is above another OHLC value")
        for field_name, value in (
            ("volume_base", self.volume_base),
            ("volume_notional", self.volume_notional),
        ):
            if value is not None and (not value.is_finite() or value < 0):
                raise CandleParseError(f"{field_name} must be a non-negative finite decimal")
        if self.trade_count is not None and (
            isinstance(self.trade_count, bool) or self.trade_count < 0
        ):
            raise CandleParseError("trade_count must be a non-negative integer")

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"

    @property
    def storage_key(self) -> tuple[Venue, str, datetime]:
        return (self.venue, self.source_symbol, self.bucket_start)

    @property
    def source_confirmed(self) -> bool:
        return self.finality == "confirmed"

    @property
    def bucket_end(self) -> datetime:
        return self.bucket_start + timedelta(minutes=1)


def require_mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CandleParseError(f"{field_name} must be an object")
    return value


def require_list(value: object, *, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise CandleParseError(f"{field_name} must be an array")
    return value


def require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandleParseError(f"{field_name} must be non-empty text")
    return value.strip()


def decimal_value(value: object, *, field_name: str, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise CandleParseError(f"{field_name} must be a decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CandleParseError(f"{field_name} must be a decimal") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        qualifier = "positive" if positive else "non-negative"
        raise CandleParseError(f"{field_name} must be a {qualifier} finite decimal")
    return number


def non_negative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise CandleParseError(f"{field_name} must be a non-negative integer")
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise CandleParseError(f"{field_name} must be a non-negative integer") from exc
    if number < 0 or str(value).strip() not in {str(number), f"{number}.0"}:
        raise CandleParseError(f"{field_name} must be a non-negative integer")
    return number


def timestamp_milliseconds(value: object, *, field_name: str) -> datetime:
    if isinstance(value, bool):
        raise CandleParseError(f"{field_name} must be epoch milliseconds")
    try:
        milliseconds = int(str(value))
    except (TypeError, ValueError) as exc:
        raise CandleParseError(f"{field_name} must be epoch milliseconds") from exc
    if milliseconds <= 0:
        raise CandleParseError(f"{field_name} must be epoch milliseconds")
    try:
        return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise CandleParseError(f"{field_name} must be epoch milliseconds") from exc


def optional_timestamp_milliseconds(value: object, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return timestamp_milliseconds(value, field_name=field_name)


def require_utc_datetime(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CandleParseError(f"{field_name} must be timezone-aware UTC")
