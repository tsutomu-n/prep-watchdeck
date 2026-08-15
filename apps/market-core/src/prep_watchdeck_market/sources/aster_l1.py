from __future__ import annotations

import asyncio
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
    safe_source_error_code,
    text,
    timestamp_from_milliseconds,
)

ASTER_L1_BASE_URL = "https://fapi.asterdex.com"
ASTER_PREMIUM_INDEX_ENDPOINT = "/fapi/v3/premiumIndex"
ASTER_BOOK_TICKER_ENDPOINT = "/fapi/v3/ticker/bookTicker"
ASTER_TICKER_24H_ENDPOINT = "/fapi/v3/ticker/24hr"
ASTER_L1_ENDPOINT = "premiumIndex+bookTicker+24hr"


async def fetch_aster_l1(
    session: aiohttp.ClientSession,
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime | None = None,
) -> MarketBatch:
    try:
        premium, book, ticker = await asyncio.gather(
            _fetch_json(session, ASTER_PREMIUM_INDEX_ENDPOINT),
            _fetch_json(session, ASTER_BOOK_TICKER_ENDPOINT),
            _fetch_json(session, ASTER_TICKER_24H_ENDPOINT),
        )
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise CatalogSourceError(
            "Aster L1 fetch failed",
            error_code=safe_source_error_code(exc),
        ) from exc
    return parse_aster_l1(
        premium_index_payload=premium,
        book_ticker_payload=book,
        ticker_24h_payload=ticker,
        instruments=instruments,
        cycle_at=cycle_at,
        observed_at=observed_at or observed_now(),
    )


async def _fetch_json(session: aiohttp.ClientSession, endpoint: str) -> object:
    async with session.get(
        f"{ASTER_L1_BASE_URL}{endpoint}",
        timeout=aiohttp.ClientTimeout(total=20),
    ) as response:
        response.raise_for_status()
        return await response.json(content_type=None)


def parse_aster_l1(
    *,
    premium_index_payload: object,
    book_ticker_payload: object,
    ticker_24h_payload: object,
    instruments: Collection[CatalogInstrument],
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketBatch:
    premium_rows = require_list(premium_index_payload, field_name="Aster premium index")
    book_rows = require_list(book_ticker_payload, field_name="Aster book ticker")
    ticker_rows = require_list(ticker_24h_payload, field_name="Aster 24h ticker")
    premium = _by_symbol(premium_rows)
    book = _by_symbol(book_rows)
    ticker = _by_symbol(ticker_rows)
    semantic_payload: JsonPayload = {
        "bookTicker": sorted(book.values(), key=_row_symbol),
        "premiumIndex": sorted(premium.values(), key=_row_symbol),
        "ticker24h": sorted(ticker.values(), key=_row_symbol),
    }
    selected = tuple(
        instrument
        for instrument in instruments
        if instrument.venue == "aster" and instrument.active
    )
    return MarketBatch(
        venue="aster",
        cycle_at=cycle_at,
        observed_at=observed_at,
        endpoint=ASTER_L1_ENDPOINT,
        payload_hash=canonical_json_sha256(semantic_payload),
        observations=tuple(
            _parse_observation(
                instrument,
                premium.get(instrument.source_symbol),
                book.get(instrument.source_symbol),
                ticker.get(instrument.source_symbol),
                cycle_at=cycle_at,
                observed_at=observed_at,
            )
            for instrument in selected
        ),
        raw_payload=semantic_payload,
    )


def _parse_observation(
    instrument: CatalogInstrument,
    premium: dict[str, object] | None,
    book: dict[str, object] | None,
    ticker: dict[str, object] | None,
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketObservation:
    raw_payload: dict[str, object] = {}
    if premium is not None:
        raw_payload["premiumIndex"] = premium
    if book is not None:
        raw_payload["bookTicker"] = book
    if ticker is not None:
        raw_payload["ticker24h"] = ticker
    if not raw_payload:
        return _empty_observation(
            instrument,
            raw_payload,
            cycle_at=cycle_at,
            observed_at=observed_at,
        )

    premium = premium or {}
    book = book or {}
    ticker = ticker or {}
    mark = positive_decimal(premium.get("markPrice"))
    reference = positive_decimal(premium.get("indexPrice"))
    funding = finite_decimal(premium.get("lastFundingRate"))
    bid = positive_decimal(book.get("bidPrice"))
    ask = positive_decimal(book.get("askPrice"))
    if bid is not None and ask is not None and ask < bid:
        bid = None
        ask = None
    volume = non_negative_decimal(ticker.get("quoteVolume"))
    next_funding_at = timestamp_from_milliseconds(premium.get("nextFundingTime"))
    source_times = (
        timestamp_from_milliseconds(premium.get("time")),
        timestamp_from_milliseconds(book.get("time")),
        timestamp_from_milliseconds(ticker.get("closeTime")),
    )
    confirmed_source_times = tuple(item for item in source_times if item is not None)
    source_at = min(confirmed_source_times) if len(confirmed_source_times) == 3 else None
    complete = all(
        value is not None
        for value in (mark, reference, funding, bid, ask, volume, next_funding_at, source_at)
    )
    interval = instrument.funding_interval_seconds
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
        next_funding_at=next_funding_at,
        open_interest_raw=None,
        open_interest_raw_unit=None,
        open_interest_base=None,
        open_interest_notional=None,
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


def _by_symbol(rows: list[object]) -> dict[str, dict[str, object]]:
    return {
        symbol: dict(row)
        for row in rows
        if isinstance(row, dict) and (symbol := text(row.get("symbol"))) is not None
    }


def _row_symbol(row: object) -> str:
    return text(row.get("symbol")) or "" if isinstance(row, dict) else ""
