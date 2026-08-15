from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from prep_watchdeck_market.models import JsonPayload, Venue

MarketStatus = Literal["ready", "partial", "unavailable", "stale"]
ReferencePriceKind = Literal["index", "oracle", "none"]


@dataclass(frozen=True, slots=True)
class MarketObservation:
    venue_instrument_id: str
    source_symbol: str
    cycle_at: datetime
    observed_at: datetime
    source_at: datetime | None
    status: MarketStatus
    mark_price: Decimal | None
    reference_price: Decimal | None
    reference_price_kind: ReferencePriceKind
    best_bid: Decimal | None
    best_ask: Decimal | None
    funding_rate_raw: Decimal | None
    funding_interval_seconds: int | None
    funding_rate_per_hour: Decimal | None
    next_funding_at: datetime | None
    open_interest_raw: Decimal | None
    open_interest_raw_unit: str | None
    open_interest_base: Decimal | None
    open_interest_notional: Decimal | None
    volume_24h_raw: Decimal | None
    volume_24h_unit: str | None
    quote_asset: str
    collateral_asset: str | None
    source_payload_hash: str
    error_code: str | None
    raw_payload: dict[str, object] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class MarketBatch:
    venue: Venue
    cycle_at: datetime
    observed_at: datetime
    endpoint: str
    payload_hash: str
    observations: tuple[MarketObservation, ...]
    raw_payload: JsonPayload = field(repr=False, compare=False)


def finite_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def positive_decimal(value: object) -> Decimal | None:
    number = finite_decimal(value)
    return number if number is not None and number > 0 else None


def non_negative_decimal(value: object) -> Decimal | None:
    number = finite_decimal(value)
    return number if number is not None and number >= 0 else None


def funding_per_hour(
    funding_rate_raw: Decimal | None,
    funding_interval_seconds: int | None,
) -> Decimal | None:
    if funding_rate_raw is None or funding_interval_seconds is None:
        return None
    if funding_interval_seconds <= 0:
        return None
    return funding_rate_raw * Decimal(3_600) / Decimal(funding_interval_seconds)
