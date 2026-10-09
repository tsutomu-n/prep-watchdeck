from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Literal

Venue = Literal["bitget", "hyperliquid", "aster", "mexc"]
SUPPORTED_VENUES: tuple[Venue, ...] = ("bitget", "hyperliquid", "aster", "mexc")
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

    def semantic_definition_sha256(self) -> str:
        """Compare definitions without identified non-contract metadata.

        Keep the full definition hash as immutable provenance. Listing lifecycle,
        normalized fields, and every unknown raw field still separate versions.
        """

        ignored: set[str] = set()
        onboard_date = self.raw_definition.get("onboardDate")
        if self.venue == "bitget":
            ignored = {"maxOrderQty", "maxMarketOrderQty", "posLimit"}
        elif (
            self.venue == "aster"
            and self.raw_definition.get("contractType") == "PERPETUAL"
            and type(onboard_date) is int
            and onboard_date > 0
        ):
            # onboardDate remains in the signature as the listing boundary.
            # Aster's extra createTime metadata drifts without a contract change.
            ignored = {"createTime"}
        elif self.venue == "mexc":
            ignored = {
                "displayName",
                "displayNameEn",
                "fn",
                "baseCoinIconUrl",
                "makerFeeRate",
                "takerFeeRate",
                "liquidationFeeRate",
                "feeRateMode",
                "feeRateType",
                "leverageFeeRates",
                "tieredFeeRates",
                "isZeroFeeRate",
                "isZeroFeeSymbol",
                "minLeverage",
                "maxLeverage",
                "countryConfigContractMaxLeverage",
                "regularMaxLeverage",
                "isMaxLeverage",
                "tempMaxLeverageLimited",
            }
        raw_definition = {
            name: value for name, value in self.raw_definition.items() if name not in ignored
        }
        return replace(self, raw_definition=raw_definition).definition_sha256()


@dataclass(frozen=True, slots=True)
class CatalogBatch:
    provenance: CatalogProvenance
    instruments: tuple[CatalogInstrument, ...]
    exclusions: tuple[CatalogExclusion, ...]
    capabilities: tuple[SourceCapability, ...]
    raw_payload: JsonPayload = field(repr=False, compare=False)


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def quantity_normalizable(instrument: CatalogInstrument) -> bool:
    if instrument.venue != "mexc":
        return instrument.quantity_unit == "base" and instrument.contract_multiplier == Decimal("1")
    raw = instrument.raw_definition
    evidence = raw.get("watchdeckQuantityEvidence")
    identity = raw.get("watchdeckIdentityEvidence")
    multiplier = instrument.contract_multiplier
    return (
        instrument.quantity_unit == "contracts"
        and multiplier is not None
        and multiplier.is_finite()
        and multiplier > 0
        and isinstance(evidence, dict)
        and evidence.get("base_per_contract") == format(multiplier, "f")
        and isinstance(identity, dict)
        and identity.get("base_asset") == instrument.base_asset
        and identity.get("price_unit") == "quote_per_base"
        and identity.get("identity_price_multiplier") == "1"
    )
