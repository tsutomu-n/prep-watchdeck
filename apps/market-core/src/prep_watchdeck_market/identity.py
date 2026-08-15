from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from prep_watchdeck_market.models import CatalogInstrument

MappingMethod = Literal["exact_base_heuristic"]
UnmappedReason = Literal[
    "inactive",
    "asset_class_not_crypto",
    "market_type_not_linear_perpetual",
    "base_asset_missing",
    "alias_required",
    "quantity_unit_unknown",
    "quantity_unit_not_base",
    "contract_multiplier_unknown",
    "contract_multiplier_not_one",
    "same_venue_collision",
]


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    venue_instrument_id: str
    group_id: str | None
    mapping_method: MappingMethod | None
    unmapped_reason: UnmappedReason | None


def resolve_market_groups(instruments: Iterable[CatalogInstrument]) -> list[IdentityResolution]:
    """Resolve conservative exact-base groups while retaining every instrument."""
    ordered = list(instruments)
    individual_reasons = [_individual_unmapped_reason(instrument) for instrument in ordered]
    eligible = [
        instrument
        for instrument, reason in zip(ordered, individual_reasons, strict=True)
        if reason is None
    ]
    candidate_counts = Counter((instrument.base_asset, instrument.venue) for instrument in eligible)
    collision_bases = {
        base_asset for (base_asset, _venue), count in candidate_counts.items() if count > 1
    }

    resolutions: list[IdentityResolution] = []
    for instrument, reason in zip(ordered, individual_reasons, strict=True):
        if reason is None and instrument.base_asset in collision_bases:
            reason = "same_venue_collision"

        if reason is not None:
            resolutions.append(
                IdentityResolution(
                    venue_instrument_id=instrument.venue_instrument_id,
                    group_id=None,
                    mapping_method=None,
                    unmapped_reason=reason,
                )
            )
            continue

        resolutions.append(
            IdentityResolution(
                venue_instrument_id=instrument.venue_instrument_id,
                group_id=f"crypto:{instrument.base_asset}:linear-perp",
                mapping_method="exact_base_heuristic",
                unmapped_reason=None,
            )
        )
    return resolutions


def _individual_unmapped_reason(instrument: CatalogInstrument) -> UnmappedReason | None:
    if not instrument.active:
        return "inactive"
    if instrument.asset_class != "crypto":
        return "asset_class_not_crypto"
    if instrument.market_type != "linear_perpetual":
        return "market_type_not_linear_perpetual"
    if not instrument.base_asset:
        return "base_asset_missing"
    if instrument.raw_definition.get("identity_alias_required") is True:
        return "alias_required"
    if instrument.quantity_unit == "unknown":
        return "quantity_unit_unknown"
    if instrument.quantity_unit != "base":
        return "quantity_unit_not_base"
    if instrument.contract_multiplier is None:
        return "contract_multiplier_unknown"
    if instrument.contract_multiplier != Decimal("1"):
        return "contract_multiplier_not_one"
    return None
