from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping
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
from prep_watchdeck_market.models import CatalogInstrument, canonical_json_sha256
from prep_watchdeck_market.sources.common import (
    observed_now,
    positive_int,
    require_list,
    require_mapping,
    timestamp_from_milliseconds,
)
from prep_watchdeck_market.sources.mexc import fetch_mexc_json, mexc_data, mexc_quantity_multiplier

MEXC_L1_ENDPOINT = "/api/v1/contract/ticker+funding_rate/{symbol}"


async def fetch_mexc_l1(
    session: aiohttp.ClientSession,
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime | None = None,
) -> MarketBatch:
    selected = [i for i in instruments if i.venue == "mexc" and i.active]
    ticker = await fetch_mexc_json(session, "/api/v1/contract/ticker")
    # Bounded parallel public funding requests; future catalog growth cannot burst unboundedly.
    limiter = asyncio.Semaphore(4)

    async def funding(item: CatalogInstrument) -> object:
        async with limiter:
            return await fetch_mexc_json(
                session, "/api/v1/contract/funding_rate/" + item.source_symbol
            )

    results = await asyncio.gather(*(funding(i) for i in selected), return_exceptions=True)
    return parse_mexc_l1(
        ticker,
        {
            i.source_symbol: r
            for i, r in zip(selected, results, strict=True)
            if not isinstance(r, BaseException)
        },
        selected,
        cycle_at=cycle_at,
        observed_at=observed_at or observed_now(),
    )


def parse_mexc_l1(
    ticker_payload: object,
    funding_payloads: Mapping[str, object],
    instruments: Collection[CatalogInstrument],
    *,
    cycle_at: datetime,
    observed_at: datetime,
) -> MarketBatch:
    rows = require_list(mexc_data(ticker_payload), field_name="MEXC tickers")
    by_symbol = {r.get("symbol"): r for r in rows if isinstance(r, dict)}
    raw = {"ticker": ticker_payload, "funding": dict(funding_payloads)}
    observations = []
    for item in instruments:
        if item.venue != "mexc" or not item.active:
            continue
        row = by_symbol.get(item.source_symbol, {})
        funding = (
            require_mapping(
                mexc_data(funding_payloads[item.source_symbol]), field_name="MEXC funding"
            )
            if item.source_symbol in funding_payloads
            else {}
        )
        if funding and funding.get("symbol") != item.source_symbol:
            funding = {}
        interval_hours = positive_int(funding.get("collectCycle"))
        interval = None if interval_hours is None else interval_hours * 3600
        rate = finite_decimal(funding.get("fundingRate"))
        mark = positive_decimal(row.get("fairPrice"))
        reference = positive_decimal(row.get("indexPrice"))
        bid, ask = positive_decimal(row.get("bid1")), positive_decimal(row.get("ask1"))
        if bid is not None and ask is not None and ask < bid:
            bid = ask = None
        oi = non_negative_decimal(row.get("holdVol"))
        base = None if oi is None else oi * mexc_quantity_multiplier(item)
        volume = non_negative_decimal(row.get("amount24"))
        next_at = timestamp_from_milliseconds(funding.get("nextSettleTime"))
        ticker_at = timestamp_from_milliseconds(row.get("timestamp"))
        funding_at = timestamp_from_milliseconds(funding.get("timestamp"))
        source_at = min(ticker_at, funding_at) if ticker_at and funding_at else None
        complete = all(
            v is not None
            for v in (mark, reference, bid, ask, oi, volume, rate, interval, next_at, source_at)
        )
        row_raw: dict[str, object] = {
            "ticker": row,
            "funding": funding,
            "watchdeckBasePerContract": format(mexc_quantity_multiplier(item), "f"),
        }
        observations.append(
            MarketObservation(
                item.venue_instrument_id,
                item.source_symbol,
                cycle_at,
                observed_at,
                source_at,
                "ready" if complete else "partial",
                mark,
                reference,
                "index" if reference else "none",
                bid,
                ask,
                rate,
                interval,
                funding_per_hour(rate, interval),
                next_at,
                oi,
                "contracts" if oi is not None else None,
                base,
                base * mark if base is not None and mark is not None else None,
                volume,
                "quote" if volume is not None else None,
                item.quote_asset,
                item.collateral_asset,
                canonical_json_sha256(row_raw),
                None if complete else "incomplete_source_row",
                row_raw,
            )
        )
    return MarketBatch(
        "mexc",
        cycle_at,
        observed_at,
        MEXC_L1_ENDPOINT,
        canonical_json_sha256(raw),
        tuple(observations),
        raw,
    )
