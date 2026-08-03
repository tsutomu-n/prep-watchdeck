from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, field_validator


class CandleBar(BaseModel):
    symbol: str
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_vol: Decimal
    quote_vol: Decimal

    @field_validator("ts")
    @classmethod
    def validate_ts(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("ts must be positive")
        return value

    @field_validator("open", "high", "low", "close")
    @classmethod
    def validate_positive_price(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("price must be positive")
        return value

    @field_validator("base_vol", "quote_vol")
    @classmethod
    def validate_non_negative_volume(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("volume must be non-negative")
        return value
