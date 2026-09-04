from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import aiohttp

from prep_watchdeck_market.models import (
    CatalogBatch,
    CatalogExclusion,
    CatalogInstrument,
    CatalogProvenance,
    JsonPayload,
    SourceCapability,
    canonical_json_sha256,
)
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    non_negative_int,
    observed_now,
    require_list,
    require_mapping,
    text,
)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_CATALOG_ENDPOINT = "/info:type=meta,dex=default"
HYPERLIQUID_DOCUMENTATION_URL = (
    "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals"
)
HYPERLIQUID_CONTRACT_DOCUMENTATION_URL = (
    "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications"
)


async def fetch_hyperliquid_catalog(
    session: aiohttp.ClientSession,
    *,
    observed_at: datetime | None = None,
) -> CatalogBatch:
    try:
        async with session.post(
            HYPERLIQUID_INFO_URL,
            json={"type": "meta"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError("Hyperliquid catalog fetch failed") from exc
    return parse_hyperliquid_catalog(payload, observed_at=observed_at or observed_now())


def parse_hyperliquid_catalog(payload: object, *, observed_at: datetime) -> CatalogBatch:
    raw_payload, meta = _hyperliquid_meta(payload)
    universe = require_list(meta.get("universe"), field_name="Hyperliquid universe")
    instruments: list[CatalogInstrument] = []
    exclusions: list[CatalogExclusion] = []

    for raw_row in universe:
        if not isinstance(raw_row, dict):
            exclusions.append(
                CatalogExclusion(
                    venue="hyperliquid",
                    source_symbol=None,
                    reason="malformed_definition",
                    raw_definition={"value": raw_row},
                )
            )
            continue
        row: dict[str, object] = raw_row
        symbol = text(row.get("name"))
        if symbol is None:
            reason = "missing_identity"
        elif ":" in symbol:
            reason = "not_default_core"
        elif row.get("isDelisted") is True:
            reason = "delisted"
        else:
            reason = None
        if reason is not None:
            exclusions.append(
                CatalogExclusion(
                    venue="hyperliquid",
                    source_symbol=symbol,
                    reason=reason,
                    raw_definition=dict(row),
                )
            )
            continue

        assert symbol is not None
        size_decimals = non_negative_int(row.get("szDecimals"))
        amount_step = Decimal(1).scaleb(-size_decimals) if size_decimals is not None else None
        # Core perps are USDT-denominated except HYPE/PURR, while all settle in USDC.
        # The exception comes from the official contract specification, not symbol inference.
        quote_asset = "USDC" if symbol in {"HYPE", "PURR"} else "USDT"
        instruments.append(
            CatalogInstrument(
                venue="hyperliquid",
                source_symbol=symbol,
                active=True,
                source_status="normal",
                asset_class="crypto",
                market_type="linear_perpetual",
                execution_model="clob",
                base_asset=symbol,
                quote_asset=quote_asset,
                settle_asset="USDC",
                collateral_asset="USDC",
                quantity_unit="base",
                contract_multiplier=Decimal("1"),
                price_tick=None,
                amount_step=amount_step,
                funding_interval_seconds=3_600,
                raw_definition=dict(row),
            )
        )

    return CatalogBatch(
        provenance=CatalogProvenance(
            venue="hyperliquid",
            source_kind="native_rest",
            endpoint=HYPERLIQUID_CATALOG_ENDPOINT,
            documentation_url=HYPERLIQUID_DOCUMENTATION_URL,
            observed_at=observed_at,
            source_at=None,
            payload_hash=canonical_json_sha256(raw_payload),
        ),
        instruments=tuple(instruments),
        exclusions=tuple(exclusions),
        capabilities=_hyperliquid_capabilities(),
        raw_payload=raw_payload,
    )


def _hyperliquid_meta(payload: object) -> tuple[JsonPayload, dict[str, object]]:
    if isinstance(payload, dict):
        return payload, require_mapping(payload, field_name="Hyperliquid metadata")
    if isinstance(payload, list):
        if len(payload) != 2:
            raise CatalogSourceError("Hyperliquid metaAndAssetCtxs must have two elements")
        meta = require_mapping(payload[0], field_name="Hyperliquid metadata")
        return meta, meta
    raise CatalogSourceError("Hyperliquid catalog must be an object or two-element array")


def _hyperliquid_capabilities() -> tuple[SourceCapability, ...]:
    return (
        SourceCapability(
            venue="hyperliquid",
            capability="catalog",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel=HYPERLIQUID_CATALOG_ENDPOINT,
            documentation_url=HYPERLIQUID_DOCUMENTATION_URL,
            details={"dex": "default_core"},
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="l1_all_market",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/info:type=metaAndAssetCtxs,dex=default",
            documentation_url=HYPERLIQUID_DOCUMENTATION_URL,
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="candle_1m",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="candle:1m",
            documentation_url=(
                "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/"
                "websocket/subscriptions"
            ),
            details={"finality": "derived_final"},
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="funding_history",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/info:type=fundingHistory,dex=default",
            documentation_url=HYPERLIQUID_DOCUMENTATION_URL,
            details={"capture": "settled_events", "catchupHours": 48},
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="open_interest",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/info:type=metaAndAssetCtxs,dex=default",
            documentation_url=HYPERLIQUID_DOCUMENTATION_URL,
            details={"rawUnit": "base"},
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="selected_depth",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="l2Book",
            documentation_url=(
                "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/"
                "websocket/subscriptions"
            ),
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="selected_trades",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="trades",
            documentation_url=(
                "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/"
                "websocket/subscriptions"
            ),
        ),
        SourceCapability(
            venue="hyperliquid",
            capability="contract_specification",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel=None,
            documentation_url=HYPERLIQUID_CONTRACT_DOCUMENTATION_URL,
            details={
                "collateral": "USDC",
                "defaultQuote": "USDT",
                "quoteExceptions": ["HYPE", "PURR"],
            },
        ),
    )
