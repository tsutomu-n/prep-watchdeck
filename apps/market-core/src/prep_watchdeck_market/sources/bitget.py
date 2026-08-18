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
    positive_int,
    require_list,
    require_mapping,
    text,
    timestamp_from_milliseconds,
)

BITGET_CATALOG_URL = "https://api.bitget.com/api/v2/mix/market/contracts"
BITGET_CATALOG_ENDPOINT = "/api/v2/mix/market/contracts"
BITGET_DOCUMENTATION_URL = (
    "https://www.bitget.com/api-doc/contract/market/Get-All-Symbols-Contracts"
)


async def fetch_bitget_catalog(
    session: aiohttp.ClientSession,
    *,
    observed_at: datetime | None = None,
) -> CatalogBatch:
    try:
        async with session.get(
            BITGET_CATALOG_URL,
            params={"productType": "USDT-FUTURES"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError("Bitget catalog fetch failed") from exc
    return parse_bitget_catalog(payload, observed_at=observed_at or observed_now())


def parse_bitget_catalog(payload: object, *, observed_at: datetime) -> CatalogBatch:
    root = require_mapping(payload, field_name="Bitget catalog")
    if root.get("code") != "00000":
        raise CatalogSourceError("Bitget catalog returned a non-success code")
    rows = require_list(root.get("data"), field_name="Bitget catalog data")
    semantic_payload = sorted(rows, key=_definition_symbol)
    instruments: list[CatalogInstrument] = []
    exclusions: list[CatalogExclusion] = []

    for raw_row in rows:
        if not isinstance(raw_row, dict):
            exclusions.append(
                CatalogExclusion(
                    venue="bitget",
                    source_symbol=None,
                    reason="malformed_definition",
                    raw_definition={"value": raw_row},
                )
            )
            continue
        row: dict[str, object] = raw_row
        symbol = text(row.get("symbol"))
        reason = _bitget_exclusion_reason(row, symbol=symbol)
        if reason is not None:
            exclusions.append(
                CatalogExclusion(
                    venue="bitget",
                    source_symbol=symbol,
                    reason=reason,
                    raw_definition=dict(row),
                )
            )
            continue

        base_asset = text(row.get("baseCoin"))
        assert symbol is not None and base_asset is not None
        interval_hours = positive_int(row.get("fundInterval"))
        instruments.append(
            CatalogInstrument(
                venue="bitget",
                source_symbol=symbol,
                active=True,
                source_status="normal",
                asset_class="crypto",
                market_type="linear_perpetual",
                execution_model="clob",
                base_asset=base_asset,
                quote_asset="USDT",
                settle_asset="USDT",
                collateral_asset="USDT",
                quantity_unit="base",
                contract_multiplier=Decimal("1"),
                price_tick=None,
                amount_step=positive_decimal(row.get("sizeMultiplier")),
                funding_interval_seconds=(
                    interval_hours * 3_600 if interval_hours is not None else None
                ),
                raw_definition=dict(row),
            )
        )

    return CatalogBatch(
        provenance=CatalogProvenance(
            venue="bitget",
            source_kind="native_rest",
            endpoint=BITGET_CATALOG_ENDPOINT,
            documentation_url=BITGET_DOCUMENTATION_URL,
            observed_at=observed_at,
            source_at=timestamp_from_milliseconds(root.get("requestTime")),
            payload_hash=canonical_json_sha256(semantic_payload),
        ),
        instruments=tuple(instruments),
        exclusions=tuple(exclusions),
        capabilities=_bitget_capabilities(),
        raw_payload=semantic_payload,
    )


def _bitget_exclusion_reason(row: dict[str, object], *, symbol: str | None) -> str | None:
    if symbol is None or text(row.get("baseCoin")) is None:
        return "missing_identity"
    if text(row.get("symbolType")) != "perpetual":
        return "not_perpetual"
    if text(row.get("symbolStatus")) != "normal":
        return "not_active"
    if text(row.get("quoteCoin")) != "USDT":
        return "not_usdt_quote"
    margin_coins = row.get("supportMarginCoins")
    if not isinstance(margin_coins, list) or "USDT" not in margin_coins:
        return "not_usdt_collateral"
    if text(row.get("isRwa")) != "NO":
        return "rwa_or_unconfirmed"
    return None


def _definition_symbol(value: object) -> str:
    return text(value.get("symbol")) or "" if isinstance(value, dict) else ""


def _bitget_capabilities() -> tuple[SourceCapability, ...]:
    return (
        SourceCapability(
            venue="bitget",
            capability="catalog",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel=BITGET_CATALOG_ENDPOINT,
            documentation_url=BITGET_DOCUMENTATION_URL,
        ),
        SourceCapability(
            venue="bitget",
            capability="l1_all_market",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/api/v2/mix/market/tickers",
            documentation_url="https://www.bitget.com/api-doc/contract/market/Get-All-Symbol-Ticker",
        ),
        SourceCapability(
            venue="bitget",
            capability="candle_1m",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/api/v2/mix/market/history-candles",
            documentation_url=(
                "https://www.bitget.com/api-doc/contract/market/Get-History-Candle-Data"
            ),
            details={"finality": "confirmed"},
        ),
        SourceCapability(
            venue="bitget",
            capability="funding_history",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/api/v3/market/history-fund-rate",
            documentation_url="https://www.bitget.com/api-doc/uta/public/Get-History-Funding-Rate",
            details={"capture": "settled_events", "catchupHours": 48},
        ),
        SourceCapability(
            venue="bitget",
            capability="open_interest",
            available=True,
            source_kind="native_rest",
            endpoint_or_channel="/api/v2/mix/market/tickers",
            documentation_url="https://www.bitget.com/api-doc/contract/market/Get-All-Symbol-Ticker",
            details={"rawUnit": "base"},
        ),
        SourceCapability(
            venue="bitget",
            capability="selected_depth",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="books",
            documentation_url="https://www.bitget.com/api-doc/contract/websocket/public/Order-Book-Channel",
        ),
        SourceCapability(
            venue="bitget",
            capability="selected_trades",
            available=True,
            source_kind="native_ws",
            endpoint_or_channel="trade",
            documentation_url="https://www.bitget.com/api-doc/contract/websocket/public/New-Trades-Channel",
        ),
    )
