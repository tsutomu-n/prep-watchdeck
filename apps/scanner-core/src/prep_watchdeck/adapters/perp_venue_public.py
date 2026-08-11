from __future__ import annotations

import asyncio
import time
from typing import Any

import pybotters

from prep_watchdeck.domain.perp_venue_comparison import (
    PerpVenueContract,
    PerpVenueObservation,
)

BITGET_CONTRACTS_URL = "https://api.bitget.com/api/v2/mix/market/contracts"
BITGET_TICKERS_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"


async def fetch_perp_venue_inputs() -> tuple[
    list[PerpVenueContract],
    list[PerpVenueObservation],
    dict[str, str],
]:
    async with pybotters.Client() as client:
        results = await asyncio.gather(
            _fetch_bitget(client),
            _fetch_hyperliquid(client),
            return_exceptions=True,
        )

    contracts: list[PerpVenueContract] = []
    observations: list[PerpVenueObservation] = []
    errors: dict[str, str] = {}
    for venue, result in zip(("bitget", "hyperliquid"), results, strict=True):
        if isinstance(result, BaseException):
            errors[venue] = type(result).__name__
            continue
        source_contracts, source_observations = result
        contracts.extend(source_contracts)
        observations.extend(source_observations)
    return contracts, observations, errors


async def _fetch_bitget(
    client: pybotters.Client,
) -> tuple[list[PerpVenueContract], list[PerpVenueObservation]]:
    async with client.get(
        BITGET_CONTRACTS_URL,
        params={"productType": "USDT-FUTURES"},
    ) as response:
        response.raise_for_status()
        contract_payload = await response.json()
    async with client.get(
        BITGET_TICKERS_URL,
        params={"productType": "USDT-FUTURES"},
    ) as response:
        response.raise_for_status()
        ticker_payload = await response.json()
    if contract_payload.get("code") != "00000" or ticker_payload.get("code") != "00000":
        raise ValueError("unexpected Bitget response")

    contracts = [_bitget_contract(item) for item in contract_payload.get("data", [])]
    observed_at_ms = _now_ms()
    observations = [
        _bitget_observation(item, observed_at_ms=observed_at_ms)
        for item in ticker_payload.get("data", [])
    ]
    return contracts, observations


async def _fetch_hyperliquid(
    client: pybotters.Client,
) -> tuple[list[PerpVenueContract], list[PerpVenueObservation]]:
    async with client.post(
        HYPERLIQUID_INFO_URL,
        data={"type": "metaAndAssetCtxs"},
    ) as response:
        response.raise_for_status()
        payload = await response.json()
    if not isinstance(payload, list) or len(payload) != 2:
        raise ValueError("unexpected Hyperliquid response")
    meta, contexts = payload
    universe = meta.get("universe")
    if not isinstance(universe, list) or not isinstance(contexts, list):
        raise ValueError("unexpected Hyperliquid response")

    observed_at_ms = _now_ms()
    contracts: list[PerpVenueContract] = []
    observations: list[PerpVenueObservation] = []
    for asset, context in zip(universe, contexts, strict=True):
        contract = _hyperliquid_contract(asset)
        contracts.append(contract)
        observations.append(
            PerpVenueObservation(
                venue="hyperliquid",
                source_symbol=contract.source_symbol,
                mark_price=_positive_float(context.get("markPx")),
                funding_rate=_optional_float(context.get("funding")),
                open_interest_base=_optional_non_negative_float(context.get("openInterest")),
                volume_24h_notional=_optional_non_negative_float(context.get("dayNtlVlm")),
                observed_at_ms=observed_at_ms,
                source_at_ms=None,
            )
        )
    return contracts, observations


def _bitget_contract(item: dict[str, Any]) -> PerpVenueContract:
    margin_coins = item.get("supportMarginCoins")
    collateral = "USDT" if isinstance(margin_coins, list) and "USDT" in margin_coins else ""
    return PerpVenueContract(
        venue="bitget",
        source_symbol=str(item.get("symbol", "")),
        asset=str(item.get("baseCoin", "")),
        quote=str(item.get("quoteCoin", "")),
        collateral=collateral,
        contract_kind=str(item.get("symbolType", "")),
        status=str(item.get("symbolStatus", "")),
        is_rwa=item.get("isRwa") != "NO",
        is_default_core=True,
        open_interest_unit="base",
        funding_interval_hours=_optional_positive_int(item.get("fundInterval")),
    )


def _bitget_observation(
    item: dict[str, Any],
    *,
    observed_at_ms: int,
) -> PerpVenueObservation:
    return PerpVenueObservation(
        venue="bitget",
        source_symbol=str(item.get("symbol", "")),
        mark_price=_positive_float(item.get("markPrice")),
        funding_rate=_optional_float(item.get("fundingRate")),
        open_interest_base=_optional_non_negative_float(item.get("holdingAmount")),
        volume_24h_notional=_optional_non_negative_float(item.get("usdtVolume")),
        observed_at_ms=observed_at_ms,
        source_at_ms=_optional_int(item.get("ts")),
    )


def _hyperliquid_contract(item: dict[str, Any]) -> PerpVenueContract:
    asset = str(item.get("name", ""))
    quote = "USDC" if asset in {"HYPE", "PURR"} else "USDT"
    return PerpVenueContract(
        venue="hyperliquid",
        source_symbol=asset,
        asset=asset,
        quote=quote,
        collateral="USDC",
        contract_kind="perpetual",
        status="off" if item.get("isDelisted") is True else "normal",
        is_rwa=False,
        is_default_core=True,
        open_interest_unit="base",
        funding_interval_hours=1,
    )


def _positive_float(value: Any) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError("mark price must be positive")
    return number


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if number >= 0 else None


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    number = int(value)
    return number if number > 0 else None


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _now_ms() -> int:
    return int(time.time() * 1_000)
