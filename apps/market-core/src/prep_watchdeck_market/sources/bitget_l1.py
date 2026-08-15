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
from prep_watchdeck_market.models import (
    CatalogInstrument,
    JsonPayload,
    canonical_json_sha256,
)
from prep_watchdeck_market.sources.common import (
    CatalogSourceError,
    observed_now,
    require_list,
    require_mapping,
    safe_source_error_code,
    text,
    timestamp_from_milliseconds,
)

BITGET_L1_URL = "https://api.bitget.com/api/v2/mix/market/tickers"
BITGET_L1_ENDPOINT = "/api/v2/mix/market/tickers"


async def fetch_bitget_l1(
    session: aiohttp.ClientSession,
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime | None = None,
) -> MarketBatch:
    try:
        async with session.get(
            BITGET_L1_URL,
            params={"productType": "USDT-FUTURES"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            response.raise_for_status()
            payload = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError(
            "Bitget L1 fetch failed",
            error_code=safe_source_error_code(exc),
        ) from exc
    return parse_bitget_l1(
        payload,
        instruments=instruments,
        cycle_at=cycle_at,
        observed_at=observed_at or observed_now(),
    )


def parse_bitget_l1(
    payload: object,
    *,
    instruments: Collection[CatalogInstrument],
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketBatch:
    root = require_mapping(payload, field_name="Bitget L1")
    if root.get("code") != "00000":
        raw_business_code = root.get("code")
        business_code = (
            str(raw_business_code)
            if isinstance(raw_business_code, (str, int)) and not isinstance(raw_business_code, bool)
            else None
        )
        raise CatalogSourceError(
            "Bitget L1 returned a non-success code",
            error_code=(
                "bitget_business_429" if business_code == "429" else "bitget_business_error"
            ),
        )
    rows = require_list(root.get("data"), field_name="Bitget L1 data")
    by_symbol = {
        symbol: dict(row)
        for row in rows
        if isinstance(row, dict) and (symbol := text(row.get("symbol"))) is not None
    }
    semantic_payload: JsonPayload = sorted(by_symbol.values(), key=_row_symbol)
    selected = tuple(
        instrument
        for instrument in instruments
        if instrument.venue == "bitget" and instrument.active
    )
    observations = tuple(
        _parse_observation(
            instrument,
            by_symbol.get(instrument.source_symbol),
            cycle_at=cycle_at,
            observed_at=observed_at,
        )
        for instrument in selected
    )
    return MarketBatch(
        venue="bitget",
        cycle_at=cycle_at,
        observed_at=observed_at,
        endpoint=BITGET_L1_ENDPOINT,
        payload_hash=canonical_json_sha256(semantic_payload),
        observations=observations,
        raw_payload=semantic_payload,
    )


def _parse_observation(
    instrument: CatalogInstrument,
    row: dict[str, object] | None,
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketObservation:
    raw = row or {}
    if row is None:
        return _observation(
            instrument,
            raw,
            cycle_at=cycle_at,
            observed_at=observed_at,
            status="unavailable",
            error_code="missing_source_row",
        )

    mark = positive_decimal(row.get("markPrice"))
    reference = positive_decimal(row.get("indexPrice"))
    bid = positive_decimal(row.get("bidPr"))
    ask = positive_decimal(row.get("askPr"))
    if bid is not None and ask is not None and ask < bid:
        bid = None
        ask = None
    funding = finite_decimal(row.get("fundingRate"))
    open_interest = non_negative_decimal(row.get("holdingAmount"))
    volume = non_negative_decimal(row.get("quoteVolume"))
    source_at = timestamp_from_milliseconds(row.get("ts"))
    interval = instrument.funding_interval_seconds
    complete = all(
        value is not None
        for value in (
            mark,
            reference,
            bid,
            ask,
            funding,
            open_interest,
            volume,
            source_at,
            interval,
        )
    )
    return MarketObservation(
        venue_instrument_id=instrument.venue_instrument_id,
        source_symbol=instrument.source_symbol,
        cycle_at=cycle_at,
        observed_at=observed_at,
        source_at=source_at,
        status="ready" if complete else "partial",
        mark_price=mark,
        reference_price=reference,
        reference_price_kind="index" if reference is not None else "none",
        best_bid=bid,
        best_ask=ask,
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
        source_payload_hash=canonical_json_sha256(raw),
        error_code=None if complete else "incomplete_source_row",
        raw_payload=raw,
    )


def _observation(
    instrument: CatalogInstrument,
    raw: dict[str, object],
    *,
    cycle_at: datetime,
    observed_at: datetime,
    status: str,
    error_code: str,
) -> MarketObservation:
    return MarketObservation(
        venue_instrument_id=instrument.venue_instrument_id,
        source_symbol=instrument.source_symbol,
        cycle_at=cycle_at,
        observed_at=observed_at,
        source_at=None,
        status=status,  # type: ignore[arg-type]
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
        source_payload_hash=canonical_json_sha256(raw),
        error_code=error_code,
        raw_payload=raw,
    )


def _row_symbol(row: object) -> str:
    return text(row.get("symbol")) or "" if isinstance(row, dict) else ""
