from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

Venue = Literal["bitget", "hyperliquid", "aster"]
QuantityUnit = Literal["base", "contracts", "unknown"]
SourceKind = Literal["native_rest", "native_ws"]
JsonPayload = dict[str, object] | list[object]


def canonical_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CatalogProvenance:
    venue: Venue
    source_kind: SourceKind
    endpoint: str
    documentation_url: str
    observed_at: datetime
    source_at: datetime | None
    payload_hash: str


@dataclass(frozen=True, slots=True)
class SourceCapability:
    venue: Venue
    capability: str
    available: bool
    source_kind: SourceKind
    endpoint_or_channel: str | None
    documentation_url: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CatalogExclusion:
    venue: Venue
    source_symbol: str | None
    reason: str
    raw_definition: dict[str, object] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class CatalogInstrument:
    venue: Venue
    source_symbol: str
    active: bool
    source_status: str
    asset_class: str
    market_type: str
    execution_model: str
    base_asset: str
    quote_asset: str
    settle_asset: str
    collateral_asset: str | None
    quantity_unit: QuantityUnit
    contract_multiplier: Decimal | None
    price_tick: Decimal | None
    amount_step: Decimal | None
    funding_interval_seconds: int | None
    raw_definition: dict[str, object] = field(repr=False, compare=False)

    @property
    def venue_instrument_id(self) -> str:
        return f"{self.venue}:{self.source_symbol}"

    def definition_sha256(self) -> str:
        return canonical_json_sha256(
            {
                "active": self.active,
                "amountStep": _decimal_text(self.amount_step),
                "assetClass": self.asset_class,
                "baseAsset": self.base_asset,
                "collateralAsset": self.collateral_asset,
                "contractMultiplier": _decimal_text(self.contract_multiplier),
                "executionModel": self.execution_model,
                "fundingIntervalSeconds": self.funding_interval_seconds,
                "marketType": self.market_type,
                "priceTick": _decimal_text(self.price_tick),
                "quantityUnit": self.quantity_unit,
                "quoteAsset": self.quote_asset,
                "rawDefinition": self.raw_definition,
                "settleAsset": self.settle_asset,
                "sourceStatus": self.source_status,
                "sourceSymbol": self.source_symbol,
                "venue": self.venue,
            }
        )


@dataclass(frozen=True, slots=True)
class CatalogBatch:
    provenance: CatalogProvenance
    instruments: tuple[CatalogInstrument, ...]
    exclusions: tuple[CatalogExclusion, ...]
    capabilities: tuple[SourceCapability, ...]
    raw_payload: JsonPayload = field(repr=False, compare=False)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
