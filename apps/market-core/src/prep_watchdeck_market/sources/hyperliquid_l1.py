from __future__ import annotations

from collections.abc import Collection
from datetime import datetime

import aiohttp

from prep_watchdeck_market.market_state import (
    MarketBatch,
    MarketObservation,
    finite_decimal,
    funding_per_hour,
    non_negative_decimal,
    positive_decimal,
)
from prep_watchdeck_market.models import CatalogInstrument, JsonPayload, canonical_json_sha256
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    observed_now,
    require_list,
    require_mapping,
    safe_source_error_code,
    text,
)

HYPERLIQUID_L1_URL = "https://api.hyperliquid.xyz/info"
HYPERLIQUID_L1_ENDPOINT = "/info:type=metaAndAssetCtxs,dex=default"


async def fetch_hyperliquid_l1(
    session: aiohttp.ClientSession,
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime | None = None,
) -> MarketBatch:
    try:
        async with session.post(
            HYPERLIQUID_L1_URL,
            json={"type": "metaAndAssetCtxs"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError(
            "Hyperliquid L1 fetch failed",
            error_code=safe_source_error_code(exc),
        ) from exc
    return parse_hyperliquid_l1(
        payload,
        instruments=instruments,
        cycle_at=cycle_at,
        observed_at=observed_at or observed_now(),
    )


def parse_hyperliquid_l1(
    payload: object,
    *,
    instruments: Collection[CatalogInstrument],
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketBatch:
    envelope = require_list(payload, field_name="Hyperliquid L1")
    if len(envelope) != 2:
        raise CatalogSourceError("Hyperliquid L1 must have two elements")
    meta = require_mapping(envelope[0], field_name="Hyperliquid L1 metadata")
    universe = require_list(meta.get("universe"), field_name="Hyperliquid L1 universe")
    contexts = require_list(envelope[1], field_name="Hyperliquid L1 contexts")
    rows: dict[str, dict[str, object]] = {}
    for index, definition_value in enumerate(universe):
        if not isinstance(definition_value, dict):
            continue
        symbol = text(definition_value.get("name"))
        context_value = contexts[index] if index < len(contexts) else None
        if symbol is not None and isinstance(context_value, dict):
            rows[symbol] = {
                "definition": dict(definition_value),
                "context": dict(context_value),
            }
    semantic_payload: JsonPayload = [meta, contexts]
    selected = tuple(
        instrument
        for instrument in instruments
        if instrument.venue == "hyperliquid" and instrument.active
    )
    return MarketBatch(
        venue="hyperliquid",
        cycle_at=cycle_at,
        observed_at=observed_at,
        endpoint=HYPERLIQUID_L1_ENDPOINT,
        payload_hash=canonical_json_sha256(semantic_payload),
        observations=tuple(
            _parse_observation(
                instrument,
                rows.get(instrument.source_symbol),
                cycle_at=cycle_at,
                observed_at=observed_at,
            )
            for instrument in selected
        ),
        raw_payload=semantic_payload,
    )


def _parse_observation(
    instrument: CatalogInstrument,
    raw: dict[str, object] | None,
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketObservation:
    raw_payload = raw or {}
    context_value = raw_payload.get("context")
    context = context_value if isinstance(context_value, dict) else None
    if context is None:
        return _empty_observation(
            instrument,
            raw_payload,
            cycle_at=cycle_at,
            observed_at=observed_at,
        )

    mark = positive_decimal(context.get("markPx"))
    oracle = positive_decimal(context.get("oraclePx"))
    funding = finite_decimal(context.get("funding"))
    open_interest = non_negative_decimal(context.get("openInterest"))
    volume = non_negative_decimal(context.get("dayNtlVlm"))
    interval = instrument.funding_interval_seconds
    complete = all(
        value is not None for value in (mark, oracle, funding, open_interest, volume, interval)
    )
    return MarketObservation(
        venue_instrument_id=instrument.venue_instrument_id,
        source_symbol=instrument.source_symbol,
        cycle_at=cycle_at,
        observed_at=observed_at,
        source_at=None,
        status="ready" if complete else "partial",
        mark_price=mark,
        reference_price=oracle,
        reference_price_kind="oracle" if oracle is not None else "none",
        best_bid=None,
        best_ask=None,
        funding_rate_raw=funding,
        funding_interval_seconds=interval,
        funding_rate_per_hour=funding_per_hour(funding, interval),
        next_funding_at=None,
        open_interest_raw=open_interest,
        open_interest_raw_unit="base" if open_interest is not None else None,
        open_interest_base=open_interest,
        open_interest_notional=(
            open_interest * mark if open_interest is not None and mark is not None else None
        ),
        volume_24h_raw=volume,
        volume_24h_unit="quote" if volume is not None else None,
        quote_asset=instrument.quote_asset,
        collateral_asset=instrument.collateral_asset,
        source_payload_hash=canonical_json_sha256(raw_payload),
        error_code=None if complete else "incomplete_source_row",
        raw_payload=raw_payload,
    )


def _empty_observation(
    instrument: CatalogInstrument,
    raw_payload: dict[str, object],
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketObservation:
    return MarketObservation(
        venue_instrument_id=instrument.venue_instrument_id,
        source_symbol=instrument.source_symbol,
        cycle_at=cycle_at,
        observed_at=observed_at,
        source_at=None,
        status="unavailable",
        mark_price=None,
        reference_price=None,
        reference_price_kind="none",
        best_bid=None,
        best_ask=None,
        funding_rate_raw=None,
        funding_interval_seconds=instrument.funding_interval_seconds,
        funding_rate_per_hour=None,
        next_funding_at=None,
        open_interest_raw=None,
        open_interest_raw_unit=None,
        open_interest_base=None,
        open_interest_notional=None,
        volume_24h_raw=None,
        volume_24h_unit=None,
        quote_asset=instrument.quote_asset,
        collateral_asset=instrument.collateral_asset,
        source_payload_hash=canonical_json_sha256(raw_payload),
        error_code="missing_source_row",
        raw_payload=raw_payload,
    )
