from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import aiohttp

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
    require_list,
    require_mapping,
    text,
    timestamp_from_milliseconds,
)

ASTER_CATALOG_URL = "https://fapi.asterdex.com/fapi/v3/exchangeInfo"
ASTER_CATALOG_ENDPOINT = "/fapi/v3/exchangeInfo"
ASTER_DOCUMENTATION_URL = (
    "https://github.com/asterdex/api-docs/blob/master/V3%28Recommended%29/EN/"
    "aster-finance-futures-api-v3.md"
)


async def fetch_aster_catalog(
    session: aiohttp.ClientSession,
    *,
    observed_at: datetime | None = None,
) -> CatalogBatch:
    try:
        async with session.get(
            ASTER_CATALOG_URL,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError("Aster catalog fetch failed") from exc
    return parse_aster_catalog(payload, observed_at=observed_at or observed_now())


def parse_aster_catalog(payload: object, *, observed_at: datetime) -> CatalogBatch:
    root = require_mapping(payload, field_name="Aster catalog")
    rows = require_list(root.get("symbols"), field_name="Aster symbols")
    semantic_payload = sorted(rows, key=_definition_symbol)
    instruments: list[CatalogInstrument] = []
    exclusions: list[CatalogExclusion] = []

    for raw_row in rows:
        if not isinstance(raw_row, dict):
            exclusions.append(
                CatalogExclusion(
                    venue="aster",
                    source_symbol=None,
                    reason="malformed_definition",
                    raw_definition={"value": raw_row},
                )
            )
            continue
        row: dict[str, object] = raw_row
        symbol = text(row.get("symbol"))
        reason = _aster_exclusion_reason(row, symbol=symbol)
        if reason is not None:
            exclusions.append(
                CatalogExclusion(
                    venue="aster",
                    source_symbol=symbol,
                    reason=reason,
                    raw_definition=dict(row),
                )
            )
            continue

        base_asset = text(row.get("baseAsset"))
        assert symbol is not None and base_asset is not None
        instruments.append(
            CatalogInstrument(
                venue="aster",
                source_symbol=symbol,
                active=True,
                source_status="TRADING",
                asset_class="crypto",
                market_type="linear_perpetual",
                execution_model="clob",
                base_asset=base_asset,
                quote_asset="USDT",
                settle_asset="USDT",
                collateral_asset="USDT",
                quantity_unit="base",
                contract_multiplier=Decimal("1"),
                price_tick=_filter_decimal(row, filter_type="PRICE_FILTER", field_name="tickSize"),
                amount_step=_filter_decimal(row, filter_type="LOT_SIZE", field_name="stepSize"),
                funding_interval_seconds=None,
                raw_definition=dict(row),
            )
        )

    return CatalogBatch(
        provenance=CatalogProvenance(
            venue="aster",
            source_kind="native_rest",
            endpoint=ASTER_CATALOG_ENDPOINT,
            documentation_url=ASTER_DOCUMENTATION_URL,
            observed_at=observed_at,
            source_at=timestamp_from_milliseconds(root.get("serverTime")),
            payload_hash=canonical_json_sha256(semantic_payload),
        ),
        instruments=tuple(instruments),
        exclusions=tuple(exclusions),
        capabilities=_aster_capabilities(),
        raw_payload=semantic_payload,
    )


def _aster_exclusion_reason(row: dict[str, object], *, symbol: str | None) -> str | None:
    if symbol is None or text(row.get("baseAsset")) is None:
        return "missing_identity"
    if text(row.get("contractType")) != "PERPETUAL":
        return "not_perpetual"
    if text(row.get("status")) != "TRADING":
        return "not_active"
    if text(row.get("underlyingType")) != "COIN":
        return "not_crypto"
    if text(row.get("quoteAsset")) != "USDT":
        return "not_usdt_quote"
    if text(row.get("marginAsset")) != "USDT":
        return "not_usdt_collateral"
    return None


def _definition_symbol(value: object) -> str:
    return text(value.get("symbol")) or "" if isinstance(value, dict) else ""


def _filter_decimal(
    row: dict[str, object],
    *,
    filter_type: str,
    field_name: str,
) -> Decimal | None:
    filters = row.get("filters")
    if not isinstance(filters, list):
        return None
    for item in filters:
        if isinstance(item, dict) and item.get("filterType") == filter_type:
            return positive_decimal(item.get(field_name))
    return None


def _aster_capabilities() -> tuple[SourceCapability, ...]:
    return (
        SourceCapability(
            venue="aster",
            capability="catalog",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel=ASTER_CATALOG_ENDPOINT,
            documentation_url=ASTER_DOCUMENTATION_URL,
        ),
        SourceCapability(
            venue="aster",
            capability="l1_all_market",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="markPrice+bookTicker+24hr",
            documentation_url=ASTER_DOCUMENTATION_URL,
        ),
        SourceCapability(
            venue="aster",
            capability="candle_1m",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="<symbol>@kline_1m",
            documentation_url=ASTER_DOCUMENTATION_URL,
            details={"finality": "confirmed", "confirmationField": "x=true"},
        ),
        SourceCapability(
            venue="aster",
            capability="open_interest",
            available=False,
            source_kind="native_rest",
            endpoint_or_channel=None,
            documentation_url=ASTER_DOCUMENTATION_URL,
            details={"reason": "official_contract_unconfirmed"},
        ),
        SourceCapability(
            venue="aster",
            capability="selected_depth",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="<symbol>@depth",
            documentation_url=ASTER_DOCUMENTATION_URL,
        ),
        SourceCapability(
            venue="aster",
            capability="selected_trades",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="<symbol>@aggTrade",
            documentation_url=ASTER_DOCUMENTATION_URL,
        ),
    )
