from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

import aiohttp

from prep_watchdeck_market.mexc_budget import MexcHttpBudget
from prep_watchdeck_market.models import (
    CatalogBatch,
    CatalogExclusion,
    CatalogInstrument,
    CatalogProvenance,
    SourceCapability,
    canonical_json_sha256,
)
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    observed_now,
    positive_decimal,
    positive_int,
    require_list,
    require_mapping,
    safe_source_error_code,
    text,
)
from prep_watchdeck_market.sources.mexc_evidence import MEXC_REVIEWED_IDENTITIES

MEXC_BASE_URL = "https://api.mexc.com"
MEXC_CATALOG_ENDPOINT = "/api/v1/contract/detail/country"
MEXC_DOCUMENTATION_URL = "https://www.mexc.com/api-docs/futures/market-endpoints/get-contract-info"
MEXC_WS_URL = "wss://contract.mexc.com/edge"


def mexc_data(payload: object) -> object:
    root = require_mapping(payload, field_name="MEXC envelope")
    if root.get("success") is not True or root.get("code") != 0:
        raise CatalogSourceError("MEXC business response rejected")
    return root.get("data")


async def fetch_mexc_json(
    session: aiohttp.ClientSession,
    endpoint: str,
    *,
    params: dict[str, str] | None = None,
    lane: Literal["foreground", "funding", "recovery"] = "foreground",
    budget: MexcHttpBudget | None = None,
) -> object:
    try:
        shared_budget = budget if budget is not None else MexcHttpBudget.from_env()

        async def admit_attempt(
            request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType
        ) -> aiohttp.ClientResponse:
            # aiohttp invokes request middleware again for its transport-level GET retry.
            await shared_budget.acquire(lane=lane, timeout_seconds=20)
            return await handler(request)

        for attempt in range(2):
            async with session.get(
                MEXC_BASE_URL + endpoint,
                params=params,
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
                middlewares=(admit_attempt,),
            ) as response:
                if response.status == 429:
                    try:
                        retry_after = max(2.0, float(response.headers.get("Retry-After", "2")))
                    except ValueError:
                        retry_after = 2.0
                    await shared_budget.cooldown(retry_after)
                    if attempt == 0:
                        continue
                response.raise_for_status()
                return await response.json(content_type=None)
        raise CatalogSourceError("MEXC public fetch failed", error_code="rate_limit")
    except (aiohttp.ClientError, TimeoutError, ValueError, RuntimeError) as exc:
        raise CatalogSourceError(
            "MEXC public fetch failed", error_code=safe_source_error_code(exc)
        ) from None


async def fetch_mexc_catalog(
    session: aiohttp.ClientSession, *, observed_at: datetime | None = None
) -> CatalogBatch:
    payload = await fetch_mexc_json(session, MEXC_CATALOG_ENDPOINT)
    return parse_mexc_catalog(payload, observed_at=observed_at or observed_now())


def parse_mexc_catalog(payload: object, *, observed_at: datetime) -> CatalogBatch:
    root = require_mapping(payload, field_name="MEXC catalog")
    rows = require_list(mexc_data(root), field_name="MEXC definitions")
    instruments: list[CatalogInstrument] = []
    exclusions: list[CatalogExclusion] = []
    for value in rows:
        row = value if isinstance(value, dict) else {"value": value}
        symbol = text(row.get("symbol"))
        evidence = MEXC_REVIEWED_IDENTITIES.get(symbol or "")
        size = positive_decimal(row.get("contractSize"))
        reason = None
        if evidence is None:
            reason = "identity_not_reviewed"
        elif any(
            row.get(k) != evidence[v]
            for k, v in (
                ("baseCoin", "base_asset"),
                ("quoteCoin", "quote_asset"),
                ("settleCoin", "settle_asset"),
            )
        ):
            reason = "identity_evidence_mismatch"
        elif row.get("futureType") != 1 or row.get("preMarket") is True:
            reason = "not_linear_perpetual"
        elif size is None or positive_decimal(row.get("volUnit")) is None:
            reason = "quantity_definition_invalid"
        elif positive_decimal(row.get("priceUnit")) is None:
            reason = "price_definition_invalid"
        if reason:
            exclusions.append(CatalogExclusion("mexc", symbol, reason, dict(row)))
            continue
        assert evidence is not None and symbol is not None and size is not None
        definition = dict(row)
        definition["watchdeckIdentityEvidence"] = dict(evidence)
        definition["watchdeckQuantityEvidence"] = {
            "quantity_unit": "contracts",
            "base_per_contract": format(size, "f"),
            "source_field": "contractSize",
            "documentation_url": MEXC_DOCUMENTATION_URL,
        }
        cycle = positive_int(row.get("collectCycle"))
        instruments.append(
            CatalogInstrument(
                venue="mexc",
                source_symbol=symbol,
                active=row.get("state") == 0,
                source_status=str(row.get("state")),
                asset_class="crypto",
                market_type="linear_perpetual",
                execution_model="clob",
                base_asset=evidence["base_asset"],
                quote_asset="USDT",
                settle_asset="USDT",
                collateral_asset="USDT",
                quantity_unit="contracts",
                contract_multiplier=size,
                price_tick=positive_decimal(row.get("priceUnit")),
                amount_step=positive_decimal(row.get("volUnit")),
                funding_interval_seconds=None if cycle is None else cycle * 3600,
                raw_definition=definition,
            )
        )
    return CatalogBatch(
        provenance=CatalogProvenance(
            "mexc",
            "native_rest",
            MEXC_CATALOG_ENDPOINT,
            MEXC_DOCUMENTATION_URL,
            observed_at,
            None,
            canonical_json_sha256(root),
        ),
        instruments=tuple(instruments),
        exclusions=tuple(exclusions),
        raw_payload=root,
        capabilities=tuple(
            SourceCapability(
                "mexc", name, True, kind, endpoint, MEXC_DOCUMENTATION_URL, dict(details)
            )
            for name, kind, endpoint, details in (
                ("catalog", "native_rest", MEXC_CATALOG_ENDPOINT, {}),
                ("l1", "native_rest", "/api/v1/contract/ticker", {}),
                ("open_interest", "native_rest", "/api/v1/contract/ticker", {"unit": "contracts"}),
                ("funding", "native_rest", "/api/v1/contract/funding_rate/{symbol}", {}),
                ("funding_history", "native_rest", "/api/v1/contract/funding_rate/history", {}),
                ("candle_1m", "native_ws", "sub.kline", {"finality": "derived_final"}),
                (
                    "depth",
                    "native_ws",
                    "sub.depth",
                    {"snapshot": "/api/v1/contract/depth/{symbol}"},
                ),
                ("trades", "native_ws", "sub.deal", {"dedup_field": "i"}),
            )
        ),
    )


def mexc_quantity_multiplier(instrument: CatalogInstrument) -> Decimal:
    """Use the exact catalog definition's contract size, never an identity price multiplier."""
    evidence = instrument.raw_definition.get("watchdeckQuantityEvidence")
    if (
        instrument.venue != "mexc"
        or instrument.quantity_unit != "contracts"
        or instrument.contract_multiplier is None
        or instrument.contract_multiplier <= 0
        or not isinstance(evidence, dict)
        or positive_decimal(evidence.get("base_per_contract")) != instrument.contract_multiplier
        or positive_decimal(instrument.raw_definition.get("contractSize"))
        != instrument.contract_multiplier
    ):
        raise ValueError("MEXC quantity definition evidence mismatch")
    return instrument.contract_multiplier
