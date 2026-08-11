from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

PERP_VENUES = ("bitget", "hyperliquid")
DEFAULT_MAX_AGE_MS = 10 * 60 * 1_000
EXCLUDED_ASSETS = frozenset({"HYPE", "PURR"})


@dataclass(frozen=True)
class PerpVenueContract:
    venue: str
    source_symbol: str
    asset: str
    quote: str
    collateral: str
    contract_kind: str
    status: str
    is_rwa: bool
    is_default_core: bool
    open_interest_unit: str | None
    funding_interval_hours: int | None


@dataclass(frozen=True)
class PerpVenueObservation:
    venue: str
    source_symbol: str
    mark_price: float
    funding_rate: float | None
    open_interest_base: float | None
    volume_24h_notional: float | None
    observed_at_ms: int
    source_at_ms: int | None = None


def build_perp_venue_comparison(
    contracts: list[PerpVenueContract],
    observations: list[PerpVenueObservation],
    *,
    generated_at_ms: int,
    errors: dict[str, str] | None = None,
    max_age_ms: int = DEFAULT_MAX_AGE_MS,
) -> dict[str, object]:
    source_errors = errors or {}
    contracts_by_asset: dict[str, dict[str, PerpVenueContract]] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    for contract in contracts:
        if not _eligible_contract(contract):
            continue
        by_venue = contracts_by_asset.setdefault(contract.asset, {})
        if contract.venue in by_venue:
            duplicate_keys.add((contract.asset, contract.venue))
        by_venue[contract.venue] = contract

    observations_by_key = {
        (item.venue, item.source_symbol): item for item in observations if item.venue in PERP_VENUES
    }
    items: list[dict[str, object]] = []
    for asset, by_venue in contracts_by_asset.items():
        if set(by_venue) != set(PERP_VENUES):
            continue
        if any((asset, venue) in duplicate_keys for venue in PERP_VENUES):
            continue
        source_items: list[dict[str, object]] = []
        valid_observations: dict[str, PerpVenueObservation] = {}
        for venue in PERP_VENUES:
            contract = by_venue[venue]
            observation = observations_by_key.get((venue, contract.source_symbol))
            error = _observation_error(
                observation,
                generated_at_ms=generated_at_ms,
                max_age_ms=max_age_ms,
            )
            if error is None:
                assert observation is not None
                valid_observations[venue] = observation
                source_items.append(_serialize_source(contract, observation))
            else:
                source_items.append(
                    _serialize_unavailable_source(
                        contract,
                        source_errors.get(venue, error),
                    )
                )

        valid_count = len(valid_observations)
        status = "ready" if valid_count == 2 else "partial" if valid_count == 1 else "unavailable"
        mark_spread_pct: float | None = None
        if valid_count == 2:
            bitget_mark = valid_observations["bitget"].mark_price
            hyperliquid_mark = valid_observations["hyperliquid"].mark_price
            mark_spread_pct = (hyperliquid_mark / bitget_mark - 1) * 100
        items.append(
            {
                "symbol": by_venue["bitget"].source_symbol,
                "asset": asset,
                "status": status,
                "markSpreadPct": mark_spread_pct,
                "sources": source_items,
            }
        )

    return {
        "schemaVersion": 1,
        "mode": "perp_venue_comparison_v1",
        "generatedAt": generated_at_ms,
        "refreshIntervalSeconds": 300,
        "items": sorted(items, key=lambda item: str(item["symbol"])),
    }


def _eligible_contract(contract: PerpVenueContract) -> bool:
    if (
        contract.venue not in PERP_VENUES
        or not contract.asset
        or contract.asset in EXCLUDED_ASSETS
        or contract.asset.startswith("1000")
        or contract.contract_kind != "perpetual"
        or contract.status != "normal"
        or contract.quote != "USDT"
        or contract.open_interest_unit != "base"
        or contract.funding_interval_hours is None
        or contract.funding_interval_hours <= 0
    ):
        return False
    if contract.venue == "bitget":
        return contract.collateral == "USDT" and not contract.is_rwa
    return contract.collateral == "USDC" and contract.is_default_core and not contract.is_rwa


def _observation_error(
    observation: PerpVenueObservation | None,
    *,
    generated_at_ms: int,
    max_age_ms: int,
) -> str | None:
    if observation is None:
        return "missing"
    age_ms = generated_at_ms - observation.observed_at_ms
    source_age_ms = (
        None if observation.source_at_ms is None else generated_at_ms - observation.source_at_ms
    )
    if (
        age_ms < 0
        or age_ms > max_age_ms
        or (source_age_ms is not None and (source_age_ms < 0 or source_age_ms > max_age_ms))
    ):
        return "stale"
    if not isfinite(observation.mark_price) or observation.mark_price <= 0:
        return "invalid"
    return None


def _serialize_source(
    contract: PerpVenueContract,
    observation: PerpVenueObservation,
) -> dict[str, object]:
    funding_rate = _finite_or_none(observation.funding_rate)
    funding_per_hour = (
        funding_rate / contract.funding_interval_hours
        if funding_rate is not None and contract.funding_interval_hours
        else None
    )
    open_interest_base = _non_negative_or_none(observation.open_interest_base)
    open_interest_notional = (
        open_interest_base * observation.mark_price
        if open_interest_base is not None and contract.open_interest_unit == "base"
        else None
    )
    return {
        "venue": contract.venue,
        "status": "ok",
        "sourceSymbol": contract.source_symbol,
        "quote": contract.quote,
        "collateral": contract.collateral,
        "markPrice": observation.mark_price,
        "fundingRate": funding_rate,
        "fundingIntervalHours": contract.funding_interval_hours,
        "fundingRatePerHour": funding_per_hour,
        "openInterestBase": open_interest_base,
        "openInterestNotional": open_interest_notional,
        "volume24hNotional": _non_negative_or_none(observation.volume_24h_notional),
        "observedAt": observation.observed_at_ms,
        "sourceAt": observation.source_at_ms,
        "error": None,
    }


def _serialize_unavailable_source(
    contract: PerpVenueContract,
    error: str,
) -> dict[str, object]:
    return {
        "venue": contract.venue,
        "status": "unavailable",
        "sourceSymbol": contract.source_symbol,
        "quote": contract.quote,
        "collateral": contract.collateral,
        "markPrice": None,
        "fundingRate": None,
        "fundingIntervalHours": contract.funding_interval_hours,
        "fundingRatePerHour": None,
        "openInterestBase": None,
        "openInterestNotional": None,
        "volume24hNotional": None,
        "observedAt": None,
        "sourceAt": None,
        "error": error,
    }


def _finite_or_none(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) else None


def _non_negative_or_none(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) and value >= 0 else None
