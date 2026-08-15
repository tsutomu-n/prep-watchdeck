from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from prep_watchdeck_market.models import CatalogInstrument, Venue, canonical_json_sha256

USD_LIKE_ASSETS = frozenset({"USD", "USDC", "USDT"})
TradeSide = Literal["buy", "sell"]


class SelectedContractError(ValueError):
    """A selected instrument or source event cannot be normalized safely."""


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: Decimal
    size_base: Decimal

    def __post_init__(self) -> None:
        if not self.price.is_finite() or self.price <= 0:
            raise SelectedContractError("depth price must be positive and finite")
        if not self.size_base.is_finite() or self.size_base <= 0:
            raise SelectedContractError("depth size must be positive and finite")


@dataclass(frozen=True, slots=True)
class SelectedDepth:
    venue: Venue
    source_symbol: str
    bids: tuple[DepthLevel, ...]
    asks: tuple[DepthLevel, ...]
    source_at: datetime | None
    received_at: datetime
    source_channel: str
    raw_payload: dict[str, object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_common(self.source_symbol, self.source_at, self.received_at, self.source_channel)
        if not self.bids or not self.asks:
            raise SelectedContractError("depth must contain both bid and ask levels")
        if len(self.bids) > 20 or len(self.asks) > 20:
            raise SelectedContractError("depth must contain at most 20 levels per side")
        if any(
            left.price <= right.price for left, right in zip(self.bids, self.bids[1:], strict=False)
        ):
            raise SelectedContractError("bids must be strictly descending")
        if any(
            left.price >= right.price for left, right in zip(self.asks, self.asks[1:], strict=False)
        ):
            raise SelectedContractError("asks must be strictly ascending")
        if self.bids[0].price >= self.asks[0].price:
            raise SelectedContractError("selected depth is crossed")

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"

    @property
    def payload_hash(self) -> str:
        return canonical_json_sha256(self.raw_payload)


@dataclass(frozen=True, slots=True)
class SelectedTrade:
    venue: Venue
    source_symbol: str
    trade_id: str
    side: TradeSide
    price: Decimal
    size_base: Decimal
    source_at: datetime | None
    received_at: datetime
    source_channel: str
    raw_payload: dict[str, object] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate_common(self.source_symbol, self.source_at, self.received_at, self.source_channel)
        if not self.trade_id.strip():
            raise SelectedContractError("trade_id must not be empty")
        if self.side not in ("buy", "sell"):
            raise SelectedContractError("trade side must be buy or sell")
        if not self.price.is_finite() or self.price <= 0:
            raise SelectedContractError("trade price must be positive and finite")
        if not self.size_base.is_finite() or self.size_base <= 0:
            raise SelectedContractError("trade size must be positive and finite")

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"

    @property
    def payload_hash(self) -> str:
        return canonical_json_sha256(self.raw_payload)


type SelectedEvent = SelectedDepth | SelectedTrade


def validate_selected_instrument(instrument: CatalogInstrument) -> None:
    assets = (instrument.quote_asset, instrument.settle_asset, instrument.collateral_asset)
    if not instrument.active:
        raise SelectedContractError("selected instrument must be active")
    if instrument.execution_model != "clob":
        raise SelectedContractError("selected instrument must use CLOB execution")
    if instrument.market_type != "linear_perpetual":
        raise SelectedContractError("selected instrument must be a linear perpetual")
    if any(asset is None or asset.upper() not in USD_LIKE_ASSETS for asset in assets):
        raise SelectedContractError("selected instrument must use USD-like quote and settlement")
    if instrument.quantity_unit != "base" or instrument.contract_multiplier != Decimal("1"):
        raise SelectedContractError("selected instrument size cannot be normalized to base units")


def _validate_common(
    source_symbol: str,
    source_at: datetime | None,
    received_at: datetime,
    source_channel: str,
) -> None:
    if not source_symbol.strip() or not source_channel.strip():
        raise SelectedContractError("source symbol and channel must not be empty")
    _require_utc(received_at, "received_at")
    if source_at is not None:
        _require_utc(source_at, "source_at")


def _require_utc(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise SelectedContractError(f"{field_name} must be timezone-aware UTC")
